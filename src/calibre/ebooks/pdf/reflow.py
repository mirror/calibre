#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import with_statement

__license__   = 'GPL v3'
__copyright__ = '2009, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

from lxml import etree

class Font(object):

    def __init__(self, spec):
        self.id = spec.get('id')
        self.size = float(spec.get('size'))
        self.color = spec.get('color')
        self.family = spec.get('family')

class Text(object):

    A = etree.XPath('descendant::a[@href]')

    def __init__(self, text, font_map, opts, log):
        self.opts, self.log = opts, log
        self.font_map = font_map
        self.top, self.left, self.width, self.height = map(float, map(text.get,
            ('top', 'left', 'width', 'height')))
        self.font = self.font_map[text.get('font')]
        self.font_size = self.font.size
        self.color = self.font.color
        self.font_family = self.font.family

        self.text_as_string = etree.tostring(text, method='text',
                encoding=unicode)

class Page(object):

    def __init__(self, page, font_map, opts, log):
        self.opts, self.log = opts, log
        self.font_map = font_map
        self.number = int(page.get('number'))
        self.width, self.height = map(float, map(page.get,
            ('width', 'height')))
        self.id = 'page%d'%self.number

        self.texts = []

        for text in page.xpath('descendant::text'):
            self.texts.append(Text(text, self.font_map, self.opts, self.log))


class PDFDocument(object):

    def __init__(self, xml, opts, log):
        self.opts, self.log = opts, log
        parser = etree.XMLParser(recover=True)
        self.root = etree.fromstring(xml, parser=parser)

        self.fonts = []
        self.font_map = {}

        for spec in self.root.xpath('//fonts'):
            self.fonts.append(Font(spec))
            self.font_map[self.fonts[-1].id] = self.fonts[-1]

        self.pages = []
        self.page_map = {}

        for page in self.root.xpath('//page'):
            page = Page(page, self.font_map, opts, log)
            self.page_map[page.id] = page
            self.pages.append(page)




