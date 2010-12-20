#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2010, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

from functools import partial

from PyQt4.Qt import QMenu, QObject, QTimer

from calibre.gui2 import error_dialog
from calibre.gui2.dialogs.delete_matching_from_device import DeleteMatchingFromDeviceDialog
from calibre.gui2.dialogs.confirm_delete import confirm
from calibre.gui2.dialogs.confirm_delete_location import confirm_location
from calibre.gui2.actions import InterfaceAction

single_shot = partial(QTimer.singleShot, 10)

class MultiDeleter(QObject):

    def __init__(self, gui, rows, callback):
        from calibre.gui2.dialogs.progress import ProgressDialog
        QObject.__init__(self, gui)
        self.model = gui.library_view.model()
        self.ids = list(map(self.model.id, rows))
        self.gui = gui
        self.failures = []
        self.deleted_ids = []
        self.callback = callback
        single_shot(self.delete_one)
        self.pd = ProgressDialog(_('Deleting...'), parent=gui,
                cancelable=False, min=0, max=len(self.ids))
        self.pd.setModal(True)
        self.pd.show()

    def delete_one(self):
        if not self.ids:
            self.cleanup()
            return
        id_ = self.ids.pop()
        title = 'id:%d'%id_
        try:
            title_ = self.model.db.title(id_, index_is_id=True)
            if title_:
                title = title_
            self.model.db.delete_book(id_, notify=False, commit=False)
            self.deleted_ids.append(id_)
        except:
            import traceback
            self.failures.append((id_, title, traceback.format_exc()))
        single_shot(self.delete_one)
        self.pd.value += 1
        self.pd.set_msg(_('Deleted') + ' ' + title)

    def cleanup(self):
        self.pd.hide()
        self.pd = None
        self.model.db.commit()
        self.model.db.clean()
        self.model.books_deleted()
        self.gui.tags_view.recount()
        self.callback(self.deleted_ids)
        if self.failures:
            msg = ['==> '+x[1]+'\n'+x[2] for x in self.failures]
            error_dialog(self.gui, _('Failed to delete'),
                    _('Failed to delete some books, click the Show Details button'
                    ' for details.'), det_msg='\n\n'.join(msg), show=True)

class DeleteAction(InterfaceAction):

    name = 'Remove Books'
    action_spec = (_('Remove books'), 'trash.png', None, _('Del'))
    action_type = 'current'

    def genesis(self):
        self.qaction.triggered.connect(self.delete_books)
        self.delete_menu = QMenu()
        self.delete_menu.addAction(_('Remove selected books'), self.delete_books)
        self.delete_menu.addAction(
                _('Remove files of a specific format from selected books..'),
                self.delete_selected_formats)
        self.delete_menu.addAction(
                _('Remove all formats from selected books, except...'),
                self.delete_all_but_selected_formats)
        self.delete_menu.addAction(
                _('Remove covers from selected books'), self.delete_covers)
        self.delete_menu.addSeparator()
        self.delete_menu.addAction(
                _('Remove matching books from device'),
                self.remove_matching_books_from_device)
        self.qaction.setMenu(self.delete_menu)
        self.delete_memory = {}

    def location_selected(self, loc):
        enabled = loc == 'library'
        for action in list(self.delete_menu.actions())[1:]:
            action.setEnabled(enabled)

    def _get_selected_formats(self, msg):
        from calibre.gui2.dialogs.select_formats import SelectFormats
        fmts = self.gui.library_view.model().db.all_formats()
        d = SelectFormats([x.lower() for x in fmts], msg, parent=self.gui)
        if d.exec_() != d.Accepted:
            return None
        return d.selected_formats

    def _get_selected_ids(self, err_title=_('Cannot delete')):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows or len(rows) == 0:
            d = error_dialog(self.gui, err_title, _('No book selected'))
            d.exec_()
            return set([])
        return set(map(self.gui.library_view.model().id, rows))

    def delete_selected_formats(self, *args):
        ids = self._get_selected_ids()
        if not ids:
            return
        fmts = self._get_selected_formats(
            _('Choose formats to be deleted'))
        if not fmts:
            return
        for id in ids:
            for fmt in fmts:
                self.gui.library_view.model().db.remove_format(id, fmt,
                        index_is_id=True, notify=False)
        self.gui.library_view.model().refresh_ids(ids)
        self.gui.library_view.model().current_changed(self.gui.library_view.currentIndex(),
                self.gui.library_view.currentIndex())
        if ids:
            self.gui.tags_view.recount()

    def delete_all_but_selected_formats(self, *args):
        ids = self._get_selected_ids()
        if not ids:
            return
        fmts = self._get_selected_formats(
            '<p>'+_('Choose formats <b>not</b> to be deleted'))
        if fmts is None:
            return
        for id in ids:
            bfmts = self.gui.library_view.model().db.formats(id, index_is_id=True)
            if bfmts is None:
                continue
            bfmts = set([x.lower() for x in bfmts.split(',')])
            rfmts = bfmts - set(fmts)
            for fmt in rfmts:
                self.gui.library_view.model().db.remove_format(id, fmt,
                        index_is_id=True, notify=False)
        self.gui.library_view.model().refresh_ids(ids)
        self.gui.library_view.model().current_changed(self.gui.library_view.currentIndex(),
                self.gui.library_view.currentIndex())
        if ids:
            self.gui.tags_view.recount()

    def remove_matching_books_from_device(self, *args):
        if not self.gui.device_manager.is_device_connected:
            d = error_dialog(self.gui, _('Cannot delete books'),
                             _('No device is connected'))
            d.exec_()
            return
        ids = self._get_selected_ids()
        if not ids:
            #_get_selected_ids shows a dialog box if nothing is selected, so we
            #do not need to show one here
            return
        to_delete = {}
        some_to_delete = False
        for model,name in ((self.gui.memory_view.model(), _('Main memory')),
                           (self.gui.card_a_view.model(), _('Storage Card A')),
                           (self.gui.card_b_view.model(), _('Storage Card B'))):
            to_delete[name] = (model, model.paths_for_db_ids(ids))
            if len(to_delete[name][1]) > 0:
                some_to_delete = True
        if not some_to_delete:
            d = error_dialog(self.gui, _('No books to delete'),
                             _('None of the selected books are on the device'))
            d.exec_()
            return
        d = DeleteMatchingFromDeviceDialog(self.gui, to_delete)
        if d.exec_():
            paths = {}
            ids = {}
            for (model, id, path) in d.result:
                if model not in paths:
                    paths[model] = []
                    ids[model] = []
                paths[model].append(path)
                ids[model].append(id)
            for model in paths:
                job = self.gui.remove_paths(paths[model])
                self.delete_memory[job] = (paths[model], model)
                model.mark_for_deletion(job, ids[model], rows_are_ids=True)
            self.gui.status_bar.show_message(_('Deleting books from device.'), 1000)

    def delete_covers(self, *args):
        ids = self._get_selected_ids()
        if not ids:
            return
        for id in ids:
            self.gui.library_view.model().db.remove_cover(id)
        self.gui.library_view.model().refresh_ids(ids)
        self.gui.library_view.model().current_changed(self.gui.library_view.currentIndex(),
                self.gui.library_view.currentIndex())


    def library_ids_deleted(self, ids_deleted, current_row=None):
        view = self.gui.library_view
        for v in (self.gui.memory_view, self.gui.card_a_view, self.gui.card_b_view):
            if v is None:
                continue
            v.model().clear_ondevice(ids_deleted)
        if current_row is not None:
            ci = view.model().index(current_row, 0)
            if ci.isValid():
                view.set_current_row(current_row)

    def delete_books(self, *args):
        '''
        Delete selected books from device or library.
        '''
        view = self.gui.current_view()
        rows = view.selectionModel().selectedRows()
        if not rows or len(rows) == 0:
            return
        # Library view is visible.
        if self.gui.stack.currentIndex() == 0:
            # Ask the user if they want to delete the book from the library or device if it is in both.
            if self.gui.device_manager.is_device_connected:
                on_device = False
                on_device_ids = self._get_selected_ids()
                for id in on_device_ids:
                    res = self.gui.book_on_device(id)
                    if res[0] or res[1] or res[2]:
                        on_device = True
                    if on_device:
                        break
                if on_device:
                    loc = confirm_location('<p>' + _('Some of the selected books are on the attached device. '
                                               '<b>Where</b> do you want the selected files deleted from?'),
                                self.gui)
                    if not loc:
                        return
                    elif loc == 'dev':
                        self.remove_matching_books_from_device()
                        return
                    elif loc == 'both':
                        self.remove_matching_books_from_device()
            # The following will run if the selected books are not on a connected device.
            # The user has selected to delete from the library or the device and library.
            if not confirm('<p>'+_('The selected books will be '
                                   '<b>permanently deleted</b> and the files '
                                   'removed from your calibre library. Are you sure?')
                                +'</p>', 'library_delete_books', self.gui):
                return
            ci = view.currentIndex()
            row = None
            if ci.isValid():
                row = ci.row()
            if len(rows) < 5:
                ids_deleted = view.model().delete_books(rows)
                self.library_ids_deleted(ids_deleted, row)
            else:
                self.__md = MultiDeleter(self.gui, rows,
                        partial(self.library_ids_deleted, current_row=row))
        # Device view is visible.
        else:
            if not confirm('<p>'+_('The selected books will be '
                                   '<b>permanently deleted</b> '
                                   'from your device. Are you sure?')
                                +'</p>', 'device_delete_books', self.gui):
                return
            if self.gui.stack.currentIndex() == 1:
                view = self.gui.memory_view
            elif self.gui.stack.currentIndex() == 2:
                view = self.gui.card_a_view
            else:
                view = self.gui.card_b_view
            paths = view.model().paths(rows)
            job = self.gui.remove_paths(paths)
            self.delete_memory[job] = (paths, view.model())
            view.model().mark_for_deletion(job, rows)
            self.gui.status_bar.show_message(_('Deleting books from device.'), 1000)

