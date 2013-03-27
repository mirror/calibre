#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

from datetime import datetime

from dateutil.tz import tzoffset

from calibre.constants import plugins
from calibre.utils.date import parse_date, local_tz, UNDEFINED_DATE
from calibre.ebooks.metadata import author_to_author_sort

_c_speedup = plugins['speedup'][0]

ONE_ONE, MANY_ONE, MANY_MANY = xrange(3)

def _c_convert_timestamp(val):
    if not val:
        return None
    try:
        ret = _c_speedup.parse_date(val.strip())
    except:
        ret = None
    if ret is None:
        return parse_date(val, as_utc=False)
    year, month, day, hour, minutes, seconds, tzsecs = ret
    try:
        return datetime(year, month, day, hour, minutes, seconds,
                tzinfo=tzoffset(None, tzsecs)).astimezone(local_tz)
    except OverflowError:
        return UNDEFINED_DATE.astimezone(local_tz)

class Table(object):

    def __init__(self, name, metadata, link_table=None):
        self.name, self.metadata = name, metadata

        # self.unserialize() maps values from the db to python objects
        self.unserialize = \
            {
                'datetime': _c_convert_timestamp,
                'bool': bool
            }.get(
                metadata['datatype'], lambda x: x)
        if name == 'authors':
            # Legacy
            self.unserialize = lambda x: x.replace('|', ',') if x else None

        self.link_table = (link_table if link_table else
                'books_%s_link'%self.metadata['table'])

class VirtualTable(Table):

    '''
    A dummy table used for fields that only exist in memory like ondevice
    '''

    def __init__(self, name, table_type=ONE_ONE, datatype='text'):
        metadata = {'datatype':datatype, 'table':name}
        self.table_type = table_type
        Table.__init__(self, name, metadata)

class OneToOneTable(Table):

    '''
    Represents data that is unique per book (it may not actually be unique) but
    each item is assigned to a book in a one-to-one mapping. For example: uuid,
    timestamp, size, etc.
    '''

    table_type = ONE_ONE

    def read(self, db):
        self.book_col_map = {}
        idcol = 'id' if self.metadata['table'] == 'books' else 'book'
        for row in db.conn.execute('SELECT {0}, {1} FROM {2}'.format(idcol,
            self.metadata['column'], self.metadata['table'])):
            self.book_col_map[row[0]] = self.unserialize(row[1])

class  PathTable(OneToOneTable):

    def set_path(self, book_id, path, db):
        self.book_col_map[book_id] = path
        db.conn.execute('UPDATE books SET path=? WHERE id=?',
                        (path, book_id))

class SizeTable(OneToOneTable):

    def read(self, db):
        self.book_col_map = {}
        for row in db.conn.execute(
                'SELECT books.id, (SELECT MAX(uncompressed_size) FROM data '
                'WHERE data.book=books.id) FROM books'):
            self.book_col_map[row[0]] = self.unserialize(row[1])

class CompositeTable(OneToOneTable):

    def read(self, db):
        self.book_col_map = {}
        d = self.metadata['display']
        self.composite_template = ['composite_template']
        self.contains_html = d.get('contains_html', False)
        self.make_category = d.get('make_category', False)
        self.composite_sort = d.get('composite_sort', False)
        self.use_decorations = d.get('use_decorations', False)

class ManyToOneTable(Table):

    '''
    Represents data where one data item can map to many books, for example:
    series or publisher.

    Each book however has only one value for data of this type.
    '''

    table_type = MANY_ONE

    def read(self, db):
        self.id_map = {}
        self.col_book_map = {}
        self.book_col_map = {}
        self.read_id_maps(db)
        self.read_maps(db)

    def read_id_maps(self, db):
        for row in db.conn.execute('SELECT id, {0} FROM {1}'.format(
                self.metadata['column'], self.metadata['table'])):
            self.id_map[row[0]] = self.unserialize(row[1])

    def read_maps(self, db):
        for row in db.conn.execute(
                'SELECT book, {0} FROM {1}'.format(
                    self.metadata['link_column'], self.link_table)):
            if row[1] not in self.col_book_map:
                self.col_book_map[row[1]] = set()
            self.col_book_map[row[1]].add(row[0])
            self.book_col_map[row[0]] = row[1]

class ManyToManyTable(ManyToOneTable):

    '''
    Represents data that has a many-to-many mapping with books. i.e. each book
    can have more than one value and each value can be mapped to more than one
    book. For example: tags or authors.
    '''

    table_type = MANY_MANY
    selectq = 'SELECT book, {0} FROM {1} ORDER BY id'

    def read_maps(self, db):
        for row in db.conn.execute(
            self.selectq.format(self.metadata['link_column'], self.link_table)):
            if row[1] not in self.col_book_map:
                self.col_book_map[row[1]] = set()
            self.col_book_map[row[1]].add(row[0])
            if row[0] not in self.book_col_map:
                self.book_col_map[row[0]] = []
            self.book_col_map[row[0]].append(row[1])

        for key in tuple(self.book_col_map.iterkeys()):
            self.book_col_map[key] = tuple(self.book_col_map[key])

class AuthorsTable(ManyToManyTable):

    def read_id_maps(self, db):
        self.alink_map = {}
        self.asort_map  = {}
        for row in db.conn.execute(
                'SELECT id, name, sort, link FROM authors'):
            self.id_map[row[0]] = self.unserialize(row[1])
            self.asort_map[row[0]] = (row[2] if row[2] else
                    author_to_author_sort(row[1]))
            self.alink_map[row[0]] = row[3]

class FormatsTable(ManyToManyTable):

    def read_id_maps(self, db):
        pass

    def read_maps(self, db):
        self.fname_map = {}
        for row in db.conn.execute('SELECT book, format, name FROM data'):
            if row[1] is not None:
                fmt = row[1].upper()
                if fmt not in self.col_book_map:
                    self.col_book_map[fmt] = set()
                self.col_book_map[fmt].add(row[0])
                if row[0] not in self.book_col_map:
                    self.book_col_map[row[0]] = []
                self.book_col_map[row[0]].append(fmt)
                if row[0] not in self.fname_map:
                    self.fname_map[row[0]] = {}
                self.fname_map[row[0]][fmt] = row[2]

        for key in tuple(self.book_col_map.iterkeys()):
            self.book_col_map[key] = tuple(sorted(self.book_col_map[key]))

    def set_fname(self, book_id, fmt, fname, db):
        self.fname_map[book_id][fmt] = fname
        db.conn.execute('UPDATE data SET name=? WHERE book=? AND format=?',
                        (fname, book_id, fmt))

class IdentifiersTable(ManyToManyTable):

    def read_id_maps(self, db):
        pass

    def read_maps(self, db):
        for row in db.conn.execute('SELECT book, type, val FROM identifiers'):
            if row[1] is not None and row[2] is not None:
                if row[1] not in self.col_book_map:
                    self.col_book_map[row[1]] = set()
                self.col_book_map[row[1]].add(row[0])
                if row[0] not in self.book_col_map:
                    self.book_col_map[row[0]] = {}
                self.book_col_map[row[0]][row[1]] = row[2]

class LanguagesTable(ManyToManyTable):

    def read_id_maps(self, db):
        ManyToManyTable.read_id_maps(self, db)
