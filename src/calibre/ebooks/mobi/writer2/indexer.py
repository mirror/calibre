#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)
from future_builtins import filter

__license__   = 'GPL v3'
__copyright__ = '2011, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

from struct import pack
from cStringIO import StringIO
from collections import OrderedDict, defaultdict

from calibre.ebooks.mobi.writer2 import RECORD_SIZE
from calibre.ebooks.mobi.utils import (encint, encode_number_as_hex,
        encode_tbs, align_block, utf8_text, detect_periodical)


class CNCX(object): # {{{

    '''
    Create the CNCX records. These are records containing all the strings from
    the NCX. Each record is of the form: <vwi string size><utf-8 encoded
    string>
    '''

    MAX_STRING_LENGTH = 500

    def __init__(self, toc, is_periodical):
        self.strings = OrderedDict()

        for item in toc.iterdescendants(breadth_first=True):
            self.strings[item.title] = 0
            if is_periodical:
                self.strings[item.klass] = 0

        self.records = []
        offset = 0
        buf = StringIO()
        for key in tuple(self.strings.iterkeys()):
            utf8 = utf8_text(key[:self.MAX_STRING_LENGTH])
            l = len(utf8)
            sz_bytes = encint(l)
            raw = sz_bytes + utf8
            if 0xfbf8 - buf.tell() < 6 + len(raw):
                # Records in PDB files cannot be larger than 0x10000, so we
                # stop well before that.
                pad = 0xfbf8 - self._ctoc.tell()
                buf.write(b'\0' * pad)
                self.records.append(buf.getvalue())
                buf.truncate(0)
                offset = len(self.records) * 0x10000
            buf.write(raw)
            self.strings[key] = offset
            offset += len(raw)

        self.records.append(align_block(buf.getvalue()))

    def __getitem__(self, string):
        return self.strings[string]
# }}}

class IndexEntry(object): # {{{

    TAG_VALUES = {
            'offset': 1,
            'size': 2,
            'label_offset': 3,
            'depth': 4,
            'class_offset': 5,
            'parent_index': 21,
            'first_child_index': 22,
            'last_child_index': 23,
    }
    RTAG_MAP = {v:k for k, v in TAG_VALUES.iteritems()}

    BITMASKS = [1, 2, 3, 4, 5, 21, 22, 23,]

    def __init__(self, offset, label_offset, depth=0, class_offset=None):
        self.offset, self.label_offset = offset, label_offset
        self.depth, self.class_offset = depth, class_offset

        self.length = 0
        self.index = 0

        self.parent_index = None
        self.first_child_index = None
        self.last_child_index = None

    def __repr__(self):
        return ('IndexEntry(offset=%r, depth=%r, length=%r, index=%r,'
                ' parent_index=%r)')%(self.offset, self.depth, self.length,
                        self.index, self.parent_index)

    @dynamic_property
    def size(self):
        def fget(self): return self.length
        def fset(self, val): self.length = val
        return property(fget=fget, fset=fset, doc='Alias for length')

    @classmethod
    def tagx_block(cls, for_periodical=True):
        buf = bytearray()

        def add_tag(tag, num_values=1):
            buf.append(tag)
            buf.append(num_values)
            # bitmask
            buf.append(1 << (cls.BITMASKS.index(tag)))
            # eof
            buf.append(0)

        for tag in xrange(1, 5):
            add_tag(tag)

        if for_periodical:
            for tag in (5, 21, 22, 23):
                add_tag(tag)

        # End of TAGX record
        for i in xrange(3): buf.append(0)
        buf.append(1)

        header = b'TAGX'
        header += pack(b'>I', 12+len(buf)) # table length
        header += pack(b'>I', 1) # control byte count

        return header + bytes(buf)

    @property
    def next_offset(self):
        return self.offset + self.length

    @property
    def tag_nums(self):
        for i in range(1, 5):
            yield i
        for attr in ('class_offset', 'parent_index', 'first_child_index',
                'last_child_index'):
            if getattr(self, attr) is not None:
                yield self.TAG_VALUES[attr]

    @property
    def entry_type(self):
        ans = 0
        for tag in self.tag_nums:
            ans |= (1 << self.BITMASKS.index(tag)) # 1 << x == 2**x
        return ans

    @property
    def bytestring(self):
        buf = StringIO()
        buf.write(encode_number_as_hex(self.index))
        et = self.entry_type
        buf.write(bytes(bytearray([et])))

        for tag in self.tag_nums:
            attr = self.RTAG_MAP[tag]
            val = getattr(self, attr)
            buf.write(encint(val))

        ans = buf.getvalue()
        return ans

# }}}

class TBS(object): # {{{

    '''
    Take the list of index nodes starting/ending on a record and calculate the
    trailing byte sequence for the record.
    '''

    def __init__(self, data, is_periodical, first=False, section_map={},
            after_first=False):
        self.section_map = section_map
        #import pprint
        #pprint.pprint(data)
        #print()
        if is_periodical:
            # The starting bytes.
            # The value is zero which I think indicates the periodical
            # index entry. The values for the various flags seem to be
            # unused. If the 0b100 is present, it means that the record
            # deals with section 1 (or is the final record with section
            # transitions).
            self.type_010 = encode_tbs(0, {0b010: 0}, flag_size=3)
            self.type_011 = encode_tbs(0, {0b010: 0, 0b001: 0},
                    flag_size=3)
            self.type_110 = encode_tbs(0, {0b100: 2, 0b010: 0},
                    flag_size=3)
            self.type_111 = encode_tbs(0, {0b100: 2, 0b010: 0, 0b001:
                0}, flag_size=3)

            if not data:
                byts = b''
                if after_first:
                    # This can happen if a record contains only text between
                    # the periodical start and the first section
                    byts = self.type_011
                self.bytestring = byts
            else:
                depth_map = defaultdict(list)
                for x in ('starts', 'ends', 'completes'):
                    for idx in data[x]:
                        depth_map[idx.depth].append(idx)
                for l in depth_map.itervalues():
                    l.sort(key=lambda x:x.offset)
                self.periodical_tbs(data, first, depth_map)
        else:
            if not data:
                self.bytestring = b''
            else:
                self.book_tbs(data, first)

    def periodical_tbs(self, data, first, depth_map):
        buf = StringIO()

        has_section_start = (depth_map[1] and
                set(depth_map[1]).intersection(set(data['starts'])))
        spanner = data['spans']
        parent_section_index = -1

        if depth_map[0]:
            # We have a terminal record

            # Find the first non periodical node
            first_node = None
            for nodes in (depth_map[1], depth_map[2]):
                for node in nodes:
                    if (first_node is None or (node.offset, node.depth) <
                            (first_node.offset, first_node.depth)):
                        first_node = node

            typ = (self.type_110 if has_section_start else self.type_010)

            # parent_section_index is needed for the last record
            if first_node is not None and first_node.depth > 0:
                parent_section_index = (first_node.index if first_node.depth
                        == 1 else first_node.parent_index)
            else:
                parent_section_index = max(self.section_map.iterkeys())

        else:
            # Non terminal record

            if spanner is not None:
                # record is spanned by a single article
                parent_section_index = spanner.parent_index
                typ = (self.type_110 if parent_section_index == 1 else
                        self.type_010)
            elif not depth_map[1]:
                # has only article nodes, i.e. spanned by a section
                parent_section_index = depth_map[2][0].parent_index
                typ = (self.type_111 if parent_section_index == 1 else
                        self.type_010)
            else:
                # has section transitions
                if depth_map[2]:
                    parent_section_index = depth_map[2][0].parent_index
                else:
                    parent_section_index = depth_map[1][0].index
                typ = self.type_011

        buf.write(typ)

        if typ not in (self.type_110, self.type_111) and parent_section_index > 0:
            extra = {}
            # Write starting section information
            if spanner is None:
                num_articles = len([a for a in depth_map[1] if a.parent_index
                    == parent_section_index])
                if not depth_map[1]:
                    extra = {0b0001: 0}
                if num_articles > 1:
                    extra = {0b0100: num_articles}
            buf.write(encode_tbs(parent_section_index, extra))

        if spanner is None:
            articles = depth_map[2]
            sections = set([self.section_map[a.parent_index] for a in
                articles])
            sections = sorted(sections, key=lambda x:x.offset)
            section_map = {s:[a for a in articles if a.parent_index ==
                s.index] for s in sections}
            for i, section in enumerate(sections):
                # All the articles in this record that belong to section
                articles = section_map[section]
                first_article = articles[0]
                last_article = articles[-1]
                num = len(articles)

                try:
                    next_sec = sections[i+1]
                except:
                    next_sec = None

                extra = {}
                if num > 1:
                    extra[0b0100] = num
                if False and i == 0 and next_sec is not None:
                    # Write offset to next section from start of record
                    # I can't figure out exactly when Kindlegen decides to
                    # write this so I have disabled it for now.
                    extra[0b0001] = next_sec.offset - data['offset']

                buf.write(encode_tbs(first_article.index-section.index, extra))

                if next_sec is not None:
                    buf.write(encode_tbs(last_article.index-next_sec.index,
                        {0b1000: 0}))
        else:
            buf.write(encode_tbs(spanner.index - parent_section_index,
                {0b0001: 0}))

        self.bytestring = buf.getvalue()

    def book_tbs(self, data, first):
        self.bytestring = b''
# }}}

class Indexer(object): # {{{

    def __init__(self, serializer, number_of_text_records,
            size_of_last_text_record, opts, oeb):
        self.serializer = serializer
        self.number_of_text_records = number_of_text_records
        self.text_size = (RECORD_SIZE * (self.number_of_text_records-1) +
                            size_of_last_text_record)
        self.oeb = oeb
        self.log = oeb.log
        self.opts = opts

        self.is_periodical = detect_periodical(self.oeb.toc, self.log)
        self.log('Generating MOBI index for a %s'%('periodical' if
            self.is_periodical else 'book'))
        self.is_flat_periodical = False
        if self.is_periodical:
            periodical_node = iter(oeb.toc).next()
            sections = tuple(periodical_node)
            self.is_flat_periodical = len(sections) == 1

        self.records = []

        self.cncx = CNCX(oeb.toc, self.is_periodical)

        if self.is_periodical:
            self.indices = self.create_periodical_index()
        else:
            self.indices = self.create_book_index()

        self.records.append(self.create_index_record())
        self.records.insert(0, self.create_header())
        self.records.extend(self.cncx.records)

        self.calculate_trailing_byte_sequences()

    def create_index_record(self): # {{{
        header_length = 192
        buf = StringIO()
        indices = self.indices

        # Write index entries
        offsets = []
        for i in indices:
            offsets.append(buf.tell())
            buf.write(i.bytestring)
        index_block = align_block(buf.getvalue())

        # Write offsets to index entries as an IDXT block
        idxt_block = b'IDXT'
        buf.truncate(0)
        for offset in offsets:
            buf.write(pack(b'>H', header_length+offset))
        idxt_block = align_block(idxt_block + buf.getvalue())
        body = index_block + idxt_block

        header = b'INDX'
        buf.truncate(0)
        buf.write(pack(b'>I', header_length))
        buf.write(b'\0'*4) # Unknown
        buf.write(pack(b'>I', 1)) # Header type? Or index record number?
        buf.write(b'\0'*4) # Unknown
        # IDXT block offset
        buf.write(pack(b'>I', header_length + len(index_block)))
        # Number of index entries
        buf.write(pack(b'>I', len(offsets)))
        # Unknown
        buf.write(b'\xff'*8)
        # Unknown
        buf.write(b'\0'*156)

        header += buf.getvalue()

        ans = header + body
        if len(ans) > 0x10000:
            raise ValueError('Too many entries (%d) in the TOC'%len(offsets))
        return ans
    # }}}

    def create_header(self): # {{{
        buf = StringIO()
        tagx_block = IndexEntry.tagx_block(self.is_periodical)
        header_length = 192

        # Ident 0 - 4
        buf.write(b'INDX')

        # Header length 4 - 8
        buf.write(pack(b'>I', header_length))

        # Unknown 8-16
        buf.write(b'\0'*8)

        # Index type: 0 - normal, 2 - inflection 16 - 20
        buf.write(pack(b'>I', 2))

        # IDXT offset 20-24
        buf.write(pack(b'>I', 0)) # Filled in later

        # Number of index records 24-28
        buf.write(pack(b'>I', len(self.records)))

        # Index Encoding 28-32
        buf.write(pack(b'>I', 65001)) # utf-8

        # Unknown 32-36
        buf.write(b'\xff'*4)

        # Number of index entries 36-40
        buf.write(pack(b'>I', len(self.indices)))

        # ORDT offset 40-44
        buf.write(pack(b'>I', 0))

        # LIGT offset 44-48
        buf.write(pack(b'>I', 0))

        # Number of LIGT entries 48-52
        buf.write(pack(b'>I', 0))

        # Number of CNCX records 52-56
        buf.write(pack(b'>I', len(self.cncx.records)))

        # Unknown 56-180
        buf.write(b'\0'*124)

        # TAGX offset 180-184
        buf.write(pack(b'>I', header_length))

        # Unknown 184-192
        buf.write(b'\0'*8)

        # TAGX block
        buf.write(tagx_block)

        num = len(self.indices)

        # The index of the last entry in the NCX
        buf.write(encode_number_as_hex(num-1))

        # The number of entries in the NCX
        buf.write(pack(b'>H', num))

        # Padding
        pad = (4 - (buf.tell()%4))%4
        if pad:
            buf.write(b'\0'*pad)

        idxt_offset = buf.tell()

        buf.write(b'IDXT')
        buf.write(pack(b'>H', header_length + len(tagx_block)))
        buf.write(b'\0')
        buf.seek(20)
        buf.write(pack(b'>I', idxt_offset))

        return align_block(buf.getvalue())
    # }}}

    def create_book_index(self): # {{{
        indices = []
        seen = set()
        id_offsets = self.serializer.id_offsets

        for node in self.oeb.toc.iterdescendants():
            try:
                offset = id_offsets[node.href]
                label = self.cncx[node.title]
            except:
                self.log.warn('TOC item %s not found in document'%node.href)
                continue
            if offset in seen:
                continue
            seen.add(offset)
            index = IndexEntry(offset, label)
            indices.append(index)

        indices.sort(key=lambda x:x.offset)

        # Set lengths
        for i, index in enumerate(indices):
            try:
                next_offset = indices[i+1].offset
            except:
                next_offset = self.serializer.body_end_offset
            index.length = next_offset - index.offset

        # Remove empty nodes
        indices = [i for i in indices if i.length > 0]

        # Set index values
        for i, index in enumerate(indices):
            index.index = i

        # Set lengths again to close up any gaps left by filtering
        for i, index in enumerate(indices):
            try:
                next_offset = indices[i+1].offset
            except:
                next_offset = self.serializer.body_end_offset
            index.length = next_offset - index.offset

        return indices

    # }}}

    def create_periodical_index(self): # {{{
        periodical_node = iter(self.oeb.toc).next()
        periodical_node_offset = self.serializer.body_start_offset
        periodical_node_size = (self.serializer.body_end_offset -
                periodical_node_offset)

        normalized_sections = []

        id_offsets = self.serializer.id_offsets

        periodical = IndexEntry(periodical_node_offset,
                self.cncx[periodical_node.title],
                class_offset=self.cncx[periodical_node.klass])
        periodical.length = periodical_node_size
        periodical.first_child_index = 1

        seen_sec_offsets = set()
        seen_art_offsets = set()

        for sec in periodical_node:
            normalized_articles = []
            try:
                offset = id_offsets[sec.href]
                label = self.cncx[sec.title]
                klass = self.cncx[sec.klass]
            except:
                continue
            if offset in seen_sec_offsets:
                continue
            seen_sec_offsets.add(offset)
            section = IndexEntry(offset, label, class_offset=klass, depth=1)
            section.parent_index = 0
            for art in sec:
                try:
                    offset = id_offsets[art.href]
                    label = self.cncx[art.title]
                    klass = self.cncx[art.klass]
                except:
                    continue
                if offset in seen_art_offsets:
                    continue
                seen_art_offsets.add(offset)
                article = IndexEntry(offset, label, class_offset=klass,
                        depth=2)
                normalized_articles.append(article)
            if normalized_articles:
                normalized_articles.sort(key=lambda x:x.offset)
                normalized_sections.append((section, normalized_articles))

        normalized_sections.sort(key=lambda x:x[0].offset)

        # Set lengths
        for s, x in enumerate(normalized_sections):
            sec, normalized_articles = x
            try:
                sec.length = normalized_sections[s+1][0].offset - sec.offset
            except:
                sec.length = self.serializer.body_end_offset - sec.offset
            for i, art in enumerate(normalized_articles):
                try:
                    art.length = normalized_articles[i+1].offset - art.offset
                except:
                    art.length = sec.offset + sec.length - art.offset

        # Filter
        for i, x in list(enumerate(normalized_sections)):
            sec, normalized_articles = x
            normalized_articles = list(filter(lambda x: x.length > 0,
                normalized_articles))
            normalized_sections[i] = (sec, normalized_articles)

        normalized_sections = list(filter(lambda x: x[0].length > 0 and x[1],
            normalized_sections))

        # Set indices
        i = 0
        for sec, articles in normalized_sections:
            i += 1
            sec.index = i
            sec.parent_index = 0

        for sec, articles in normalized_sections:
            for art in articles:
                i += 1
                art.index = i
                art.parent_index = sec.index

        for sec, normalized_articles in normalized_sections:
            sec.first_child_index = normalized_articles[0].index
            sec.last_child_index = normalized_articles[-1].index

        # Set lengths again to close up any gaps left by filtering
        for s, x in enumerate(normalized_sections):
            sec, articles = x
            try:
                next_offset = normalized_sections[s+1][0].offset
            except:
                next_offset = self.serializer.body_end_offset
            sec.length = next_offset - sec.offset

            for a, art in enumerate(articles):
                try:
                    next_offset = articles[a+1].offset
                except:
                    next_offset = sec.next_offset
                art.length = next_offset - art.offset

        # Sanity check
        for s, x in enumerate(normalized_sections):
            sec, articles = x
            try:
                next_sec = normalized_sections[s+1][0]
            except:
                if (sec.length == 0 or sec.next_offset !=
                        self.serializer.body_end_offset):
                    raise ValueError('Invalid section layout')
            else:
                if next_sec.offset != sec.next_offset or sec.length == 0:
                    raise ValueError('Invalid section layout')
            for a, art in enumerate(articles):
                try:
                    next_art = articles[a+1]
                except:
                    if (art.length == 0 or art.next_offset !=
                            sec.next_offset):
                        raise ValueError('Invalid article layout')
                else:
                    if art.length == 0 or art.next_offset != next_art.offset:
                        raise ValueError('Invalid article layout')

        # Flatten
        indices = [periodical]
        for sec, articles in normalized_sections:
            indices.append(sec)
            periodical.last_child_index = sec.index

        for sec, articles in normalized_sections:
            for a in articles:
                indices.append(a)

        return indices
    # }}}

    # TBS {{{
    def calculate_trailing_byte_sequences(self):
        self.tbs_map = {}
        found_node = False
        sections = [i for i in self.indices if i.depth == 1]
        section_map = OrderedDict((i.index, i) for i in
                sorted(sections, key=lambda x:x.offset))

        deepest = max(i.depth for i in self.indices)

        for i in xrange(self.number_of_text_records):
            offset = i * RECORD_SIZE
            next_offset = offset + RECORD_SIZE
            data = {'ends':[], 'completes':[], 'starts':[],
                    'spans':None, 'offset':offset, 'record_number':i+1}

            for index in self.indices:
                if index.offset >= next_offset:
                    # Node starts after current record
                    if index.depth == deepest:
                        break
                    else:
                        continue
                if index.next_offset <= offset:
                    # Node ends before current record
                    continue
                if index.offset >= offset:
                    # Node starts in current record
                    if index.next_offset <= next_offset:
                        # Node ends in current record
                        data['completes'].append(index)
                    else:
                        data['starts'].append(index)
                else:
                    # Node starts before current records
                    if index.next_offset <= next_offset:
                        # Node ends in current record
                        data['ends'].append(index)
                    elif index.depth == deepest:
                        data['spans'] = index

            if (data['ends'] or data['completes'] or data['starts'] or
                    data['spans'] is not None):
                self.tbs_map[i+1] = TBS(data, self.is_periodical, first=not
                        found_node, section_map=section_map)
                found_node = True
            else:
                self.tbs_map[i+1] = TBS({}, self.is_periodical, first=False,
                        after_first=found_node, section_map=section_map)

    def get_trailing_byte_sequence(self, num):
        return self.tbs_map[num].bytestring
    # }}}

# }}}

