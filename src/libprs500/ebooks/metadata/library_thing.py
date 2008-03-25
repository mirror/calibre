__license__   = 'GPL v3'
__copyright__ = '2008, Kovid Goyal <kovid at kovidgoyal.net>'
'''
Fetch cover from LibraryThing.com based on ISBN number.
'''

import sys, socket, os

from libprs500 import browser as _browser, OptionParser
from libprs500.ebooks.BeautifulSoup import BeautifulSoup 
browser = None

class LibraryThingError(Exception):
    pass

class ISBNNotFound(LibraryThingError):
    pass

class ServerBusy(LibraryThingError):
    pass

def login(username, password, force=True):
    global browser
    if browser is not None and not force:
        return
    browser = _browser()
    browser.open('http://www.librarything.com')
    browser.select_form('signup')
    browser['formusername'] = username
    browser['formpassword'] = password
    browser.submit()
    

def cover_from_isbn(isbn, timeout=5.):
    global browser
    if browser is None:
        browser = _browser()
    _timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)                
    try:
        src = browser.open('http://www.librarything.com/isbn/'+isbn).read()
        s = BeautifulSoup(src)
        url = s.find('td', attrs={'class':'left'})
        if url is None:
            if s.find('div', attrs={'class':'highloadwarning'}) is not None:
                raise ServerBusy(_('Could not fetch cover as server is experiencing high load. Please try again later.'))
            raise ISBNNotFound('ISBN: '+isbn+_(' not found.'))
        url = url.find('img')
        if url is None:
            raise LibraryThingError(_('Server error. Try again later.'))
        url = url['src']
        cover_data = browser.open(url).read()
        return cover_data, url.rpartition('.')[-1]
    finally:
        socket.setdefaulttimeout(_timeout)

def option_parser():
    parser = OptionParser(usage=\
'''
%prog [options] ISBN

Fetch a cover image for the book identified by ISBN from LibraryThing.com
''')
    parser.add_option('-u', '--username', default=None, 
                      help='Username for LibraryThing.com')
    parser.add_option('-p', '--password', default=None, 
                      help='Password for LibraryThing.com')
    return parser

def main(args=sys.argv):
    parser = option_parser()
    opts, args = parser.parse_args(args)
    if len(args) != 2:
        parser.print_help()
        return 1
    isbn = args[1]
    if opts.username and opts.password:
        login(opts.username, opts.password)
        
    cover_data, ext = cover_from_isbn(isbn)
    if not ext:
        ext = 'jpg'
    oname = os.path.abspath(isbn+'.'+ext)
    open(oname, 'w').write(cover_data)
    print 'Cover saved to file', oname
    return 0

if __name__ == '__main__':
    sys.exit(main())