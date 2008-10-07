#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (C) 2006 Søren Roug, European Environment Agency
#
# This is free software.  You may redistribute it under the terms
# of the Apache license and the GNU General Public License Version
# 2 or at your option any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Contributor(s):
#
import zipfile, sys, re
import xml.sax.saxutils
from cStringIO import StringIO

from odf.namespaces import OFFICENS, DCNS, METANS
from calibre.ebooks.metadata import MetaInformation, string_to_authors

whitespace = re.compile(r'\s+')

fields = {
'title':            (DCNS,u'title'),
'description':      (DCNS,u'description'),
'subject':          (DCNS,u'subject'),
'creator':          (DCNS,u'creator'),
'date':             (DCNS,u'date'),
'language':         (DCNS,u'language'),
'generator':        (METANS,u'generator'),
'initial-creator':  (METANS,u'initial-creator'),
'keyword':          (METANS,u'keyword'),
'editing-duration': (METANS,u'editing-duration'),
'editing-cycles':   (METANS,u'editing-cycles'),
'printed-by':       (METANS,u'printed-by'),
'print-date':       (METANS,u'print-date'),
'creation-date':    (METANS,u'creation-date'),
'user-defined':     (METANS,u'user-defined'),
#'template':         (METANS,u'template'),
}

def normalize(str):
    """ 
    The normalize-space function returns the argument string with whitespace
    normalized by stripping leading and trailing whitespace and replacing
    sequences of whitespace characters by a single space.
    """
    return whitespace.sub(' ', str).strip()

class MetaCollector:
    """
    The MetaCollector is a pseudo file object, that can temporarily ignore write-calls
    It could probably be replaced with a StringIO object.
    """
    def __init__(self):
        self._content = []
        self.dowrite = True

    def write(self, str):
        if self.dowrite:
            self._content.append(str)

    def content(self):
        return ''.join(self._content)


class odfmetaparser(xml.sax.saxutils.XMLGenerator):
    """ Parse a meta.xml file with an event-driven parser and replace elements.
        It would probably be a cleaner approach to use a DOM based parser and
        then manipulate in memory.
        Small issue: Reorders elements
    """

    def __init__(self, deletefields={}, yieldfields={}, addfields={}):
        self.deletefields = deletefields
        self.yieldfields = yieldfields
        self.addfields = addfields
        self._mimetype = ''
        self.output = MetaCollector()
        self._data = []
        self.seenfields = {}
        xml.sax.saxutils.XMLGenerator.__init__(self, self.output, 'utf-8')

    def startElementNS(self, name, qname, attrs):
        self._data = []
        field = name
# I can't modify the template until the tool replaces elements at the same
# location and not at the end
#       if name == (METANS,u'template'):
#           self._data = [attrs.get((XLINKNS,u'title'),'')]
        if name == (METANS,u'user-defined'):
            field = attrs.get((METANS,u'name'))
        if field in self.deletefields:
            self.output.dowrite = False
        elif field in self.yieldfields:
            del self.addfields[field]
            xml.sax.saxutils.XMLGenerator.startElementNS(self, name, qname, attrs)
        else:
            xml.sax.saxutils.XMLGenerator.startElementNS(self, name, qname, attrs)
        self._tag = field

    def endElementNS(self, name, qname):
        field = name
        if name == (METANS,u'user-defined'):
            field = self._tag
        if name == (OFFICENS,u'meta'):
            for k,v in self.addfields.items():
                if len(v) > 0:
                    if type(k) == type(''):
                        xml.sax.saxutils.XMLGenerator.startElementNS(self,(METANS,u'user-defined'),None,{(METANS,u'name'):k})
                        xml.sax.saxutils.XMLGenerator.characters(self, v)
                        xml.sax.saxutils.XMLGenerator.endElementNS(self, (METANS,u'user-defined'),None)
                    else:
                        xml.sax.saxutils.XMLGenerator.startElementNS(self, k, None, {})
                        xml.sax.saxutils.XMLGenerator.characters(self, v)
                        xml.sax.saxutils.XMLGenerator.endElementNS(self, k, None)
        if isinstance(self._tag, tuple):
            texttag = self._tag[1]
        else:
            texttag = self._tag
        self.seenfields[texttag] = self.data()
    
        if field in self.deletefields:
            self.output.dowrite = True
        else:
            xml.sax.saxutils.XMLGenerator.endElementNS(self, name, qname)

    def characters(self, content):
        xml.sax.saxutils.XMLGenerator.characters(self, content)
        self._data.append(content)

    def meta(self):
        return self.output.content()

    def data(self):
        return normalize(''.join(self._data))
        
def get_metadata(stream):
    zin = zipfile.ZipFile(stream, 'r')
    odfs = odfmetaparser()
    parser = xml.sax.make_parser()
    parser.setFeature(xml.sax.handler.feature_namespaces, 1)
    parser.setContentHandler(odfs)
    content = zin.read('meta.xml')
    parser.parse(StringIO(content))
    data = odfs.seenfields
    mi = MetaInformation(None, [])
    if data.has_key('title'):
        mi.title = data['title']
    if data.has_key('creator'):
        mi.authors = string_to_authors(data['creator'])
    if data.has_key('description'):
        mi.comments = data['description']
    if data.has_key('language'):
        mi.language = data['language']
    if data.get('keywords', ''):
        mi.tags = data['keywords'].split(',')
    
    return mi

def main(args=sys.argv):
    if len(args) != 2:
        print 'Usage: %s file.odt'%args[0]
        return 1
    mi = get_metadata(open(args[1], 'rb'))
    print mi
    return 0

if __name__ == '__main__':
    sys.exit(main())

#now = time.localtime()[:6]
#outputfile = "-"
#writemeta = False   # Do we change any meta data?
#usenormalize = False
#
#try:
#    opts, args = getopt.getopt(sys.argv[1:], "cdlI:A:a:o:x:X:")
#except getopt.GetoptError:
#    exitwithusage()
#
#if len(opts) == 0:
#    opts = [ ('-l','') ]
#
#for o, a in opts:
#    if o in ('-a','-A','-I'):
#        writemeta = True
#        if a.find(":") >= 0:
#            k,v = a.split(":",1)
#        else:
#            k,v = (a, "")
#        if len(k) == 0:
#            exitwithusage()
#        k = fields.get(k,k)
#        addfields[k] = unicode(v,'utf-8')
#    if o == '-a':
#        yieldfields[k] = True
#    if o == '-I':
#        deletefields[k] = True
#    if o == '-d':
#        writemeta = True
#        addfields[(DCNS,u'date')] = "%04d-%02d-%02dT%02d:%02d:%02d" % now
#        deletefields[(DCNS,u'date')] = True
#    if o == '-c':
#        usenormalize = True
#    if o == '-l':
#        Xfields = fields.values()
#    if o == "-x":
#        xfields.append(fields.get(a,a))
#    if o == "-X":
#        Xfields.append(fields.get(a,a))
#    if o == "-o":
#        outputfile = a
#
## The specification says we should change the element to our own,
## and must not export the original identifier.
#if writemeta:
#    addfields[(METANS,u'generator')] = TOOLSVERSION
#    deletefields[(METANS,u'generator')] = True
#
#odfs = odfmetaparser()
#parser = xml.sax.make_parser()
#parser.setFeature(xml.sax.handler.feature_namespaces, 1)
#parser.setContentHandler(odfs)
#
#if len(args) == 0:
#    zin = zipfile.ZipFile(sys.stdin,'r')
#else:
#    if not zipfile.is_zipfile(args[0]):
#        exitwithusage()
#    zin = zipfile.ZipFile(args[0], 'r')
#
#content = zin.read('meta.xml')
#parser.parse(StringIO(content))
#
#if writemeta:
#    if outputfile == '-':
#        if sys.stdout.isatty():
#           sys.stderr.write("Won't write ODF file to terminal\n")
#           sys.exit(1)
#        zout = zipfile.ZipFile(sys.stdout,"w")
#    else:
#        zout = zipfile.ZipFile(outputfile,"w")
#
#
#
#    # Loop through the input zipfile and copy the content to the output until we
#    # get to the meta.xml. Then substitute.
#    for zinfo in zin.infolist():
#        if zinfo.filename == "meta.xml":
#            # Write meta
#            zi = zipfile.ZipInfo("meta.xml", now)
#            zi.compress_type = zipfile.ZIP_DEFLATED
#            zout.writestr(zi,odfs.meta() )
#        else:
#            payload = zin.read(zinfo.filename)
#            zout.writestr(zinfo, payload)
#
#    zout.close()
#zin.close()
