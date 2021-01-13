"""
This file is part of Urtext for Sublime Text.

Urtext is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Urtext is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Urtext.  If not, see <https://www.gnu.org/licenses/>.

"""
import sublime
import sublime_plugin
import os
import re
import datetime
import time
import concurrent.futures
import subprocess
import webbrowser
from sublime_plugin import EventListener
import urllib
import json

_SublimeUrtextWindows = {}
urtext_initiated = False
quick_panel_waiting = False
quick_panel_active  = False
quick_panel_id = 0
is_browsing_history = False
node_id_regex = r'\b[0-9,a-z]{3}\b'

URL = 'http://127.0.0.1:5000/'
WATCHDOG = False

def urtext_get(endpoint, values={}):
    data = urllib.parse.urlencode(values)
    data = data.encode('ascii') 
    r = urllib.request.urlopen('http://127.0.0.1:5000/'+endpoint, data)
    response = r.read().decode('utf-8')
    return json.loads(response)

class UrtextTextCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view
        self.window = view.window()

def get_path(view):
    """ 
    given a view or None, establishes the current active path,
    either from the view or from the current active window.
    """

    current_path = None
    if view and view.file_name():
        return os.path.dirname(view.file_name())
    window = sublime.active_window()
    if not window:
        print('No active window')
        return None
    window_variables = window.extract_variables()
    if 'folder' in window_variables:
        return window.extract_variables()['folder']
    return None

#DONE
class ListProjectsCommand(sublime_plugin.TextCommand):
    
    def run(self, view):
        self.r = urtext_get('projects')

        show_panel(
            self.view.window(), 
            [t for t in self.r['projects']],
            self.set_window_project)

    def set_window_project(self, selection):
        s = urtext_get('set-project',{ 'title' : self.r['projects'][selection]})
        self.view.set_status('urtext_project', 'Urtext Project: '+s['title'])
        _SublimeUrtextWindows[self.view.window().id()] = s['path']
        node_id = s['nav_current']
        open_urtext_node(self.view, s['filename'], node_id, s['position'])

#DONE
class MoveFileToAnotherProjectCommand(UrtextTextCommand):
    
    def run(self, view):
        r = urtext_get('projects')
        show_panel(self.window, r['projects'], self.move_file)

    def move_file(self, new_project_title):
                
        replace_links = sublime.yes_no_cancel_dialog(
            'Do you want to also rewrite links to nodes in this file as links to the new project?')
        replace_links = True if replace_links == sublime.DIALOG_YES else False
        filename = self.view.file_name()

        s = urtext_get('move-file', {
            'filename' : filename, 
            'new_project':new_project_title, 
            'replace_links' : str(replace_links)
            })

        self.view.window().run_command('close_file')

        last_node = s['last_node']
        if last_node:
            open_urtext_node(self.view, last_node)

        if s['success'] != 'True':
            sublime.message_dialog('File was moved but error occured. Check the console.')
        else:
            sublime.message_dialog('File was moved')

#DONE
class UrtextHomeCommand(sublime_plugin.TextCommand):
    
    def run(self, view):
        s = urtext_get('home', {'project':get_path(self.view)})
        if 'filename' in s:
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])
#DONE
class NavigateBackwardCommand(sublime_plugin.TextCommand):

    def run(self, view):
        s = urtext_get('nav-back')
        if s['nav_current'] != 'NONE':
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])
#DONE
class NavigateForwardCommand(sublime_plugin.TextCommand):

    def run(self, view):
        s = urtext_get('nav-forward')
        if s['nav_current'] != 'NONE':
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])

#DONE
class OpenUrtextLinkCommand(sublime_plugin.TextCommand):

    def run(self, view):
        position = self.view.sel()[0].a
        column = self.view.rowcol(position)[1]
        full_line = self.view.substr(self.view.line(self.view.sel()[0]))
        s = urtext_get('get-link-set-project', {'line' : full_line, 'column' : column})
        
        kind = s['link_kind']

        if kind == 'EDITOR_LINK':
            file_view = self.view.window().open_file(s['link'])

        if kind == 'NODE':
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])

        if kind == 'HTTP':
            success = webbrowser.get().open(s['link'])
            if not success:
                self.log('Could not open tab using your "web_browser_path" setting')       

        if kind == 'FILE':
            open_external_file(s['link'])

#DONE
# class TakeSnapshot(EventListener):

#     def __init__(self):
#         self.last_time = time.time()

#     def on_modified(self, view):
#         global is_browsing_history
#         if is_browsing_history:
#             return
#         now = time.time()
#         if now - self.last_time < 10:
#             return None
#         self.last_time = now 
#         take_snapshot(view, os.path.dirname(view.file_name()))


def take_snapshot(view, project):
    contents = get_contents(view)
    if view:
        filename = os.path.basename(view.file_name())
        s = urtext_get('snapshot', {
            'project': project,
            'filename':filename, 
            'contents':contents})
        
class ToggleHistoryTraverse(UrtextTextCommand):
    """ Toggles history traversing on/off """

    def run(self):
        global is_browsing_history
        window = self.view.window()
        history_view = None
        for view in window.views():
            if view.name() == 'urtext_history': 
                history_view = view

        if history_view:
            history_group = window.get_view_index(history_view)[0]
            history_view.close()
            file_view = window.active_view_in_group(history_group-1)
            window.focus_group(history_group-1)
            window.focus_view(file_view)
            groups = window.num_groups()                
            groups -= 1
            if groups == 0:
                groups = 1
            window.focus_group(groups-1) 
            if file_view:
                size_to_groups(groups, file_view)
            is_browsing_history = False  
            return
    
        is_browsing_history = True

        # take a snapshot now so we don't mess up what's there, in case it isn't saved:
        take_snapshot(self.view, self._UrtextProjectList.current_project)

        groups = self.view.window().num_groups()
        size_to_groups(groups + 1, self.view)

        window = self.view.window()
        history_group = window.active_group() + 1
        window.focus_group(history_group)
        history_view = window.new_file()
        history_view.set_scratch(True)
        history_view.set_name('urtext_history')
        history_view.set_status('urtext_history', 'History: On')
        history_view.run_command("insert_snippet", {"contents": ''}) # this just triggers on_modified()

class TraverseHistoryView(EventListener):

    def __init__(self):
        self.current_file = None
        self.history = None
        self.string_timestamps = None
        self.rewriting = False
    
    def on_selection_modified(self, view):

        if view.name() != 'urtext_history':
            return None
        if self.rewriting:
            return

        history_view = view

        # 1-indexed number of current groups ("group" = window division)
        self.groups = history_view.window().num_groups()        

        # 0-indexed number of the group with the history view
        # history group is always made to be the view this was called from.
        self.history_group = history_view.window().active_group() 

        # 0-indexed number of the group with the content 
        # (may not yet exist)
        self.content_group = self.history_group -1

        # TAB of the content (left) view. ("sheet" = tab)        
        self.content_tab = history_view.window().active_sheet_in_group(self.content_group)

        # View of the file in the content tab 
        self.file_view = self.content_tab.view()

        filename = self.file_view.file_name()

        if self.current_file != filename:
            self.current_file = filename

        new_history = _UrtextProjectList.current_project.get_history(self.current_file)

        if not new_history:
            return None

        ts_format =  _UrtextProjectList.current_project.settings['timestamp_format']
        string_timestamps = [datetime.datetime.fromtimestamp(int(i)).strftime(ts_format) for i in sorted(new_history.keys(),reverse=True)]

        if string_timestamps != self.string_timestamps or not get_contents(history_view).strip():
            self.string_timestamps = string_timestamps
            self.history = new_history
            self.rewriting = True
            history_view.set_read_only(False)
            history_view.run_command("select_all")
            history_view.run_command("right_delete")
            history_view.run_command("insert_snippet", {"contents": 'HISTORY for '+ os.path.basename(filename)+'\n'})        
            for line in self.string_timestamps:
                history_view.run_command("insert_snippet", {"contents": line+'\n'})
            self.rewriting = False
            history_view.set_read_only(True)
            history_view.sel().clear()
            history_view.sel().add(sublime.Region(0,0))
            history_view.set_viewport_position((0,0))
            return

        line = view.substr(history_view.line(history_view.sel()[0]))
        if line in self.string_timestamps:             
            index = self.string_timestamps.index(line) 
            self.show_state(index)

    def show_state(self, index):
        state = _UrtextProjectList.current_project.apply_patches(self.history, distance_back=index)
        self.file_view.run_command("select_all")
        self.file_view.run_command("right_delete")
        for line in state.split('\n'):
            self.file_view.run_command("append", {"characters": line+ "\n" })
#DONE
class NodeBrowserCommand(sublime_plugin.TextCommand):
    
    def run(self, edit):
        self.menu = NodeBrowserMenu(project=get_path(self.view))
        show_panel(
            self.view.window(), 
            self.menu.display_menu, 
            self.open_the_file)

    def open_the_file(self, selected_option):        
        selected_item = self.menu.full_menu[selected_option]
        s = urtext_get('set-project', { 'title' : selected_item.project_title })
        s = urtext_get('nav', {'node' : selected_item.node_id })
        open_urtext_node(
            self.view, 
            selected_item.filename, 
            selected_item.node_id, 
            position=selected_item.position)

def show_panel(window, menu, main_callback):
    """ shows a quick panel with an option to cancel if -1 """
    def private_callback(index):
        if index == -1:
            return
        # otherwise return the main callback with the index of the selected item
        return main_callback(index)
    window.show_quick_panel(menu, private_callback)


#DONE
class NodeBrowserMenu:
    """ custom class to store more information on menu items than is displayed """

    def __init__(self, project='', nodes=''):
        self.full_menu = make_node_menu(
            project=project,
            nodes=nodes)
        self.display_menu = make_display_menu(self.full_menu)

#TODO fix, returns all nodes
class BacklinksBrowser(NodeBrowserCommand):

    def run(self, view):
        node_id = get_node_id(self.view)
        s = urtext_get('backlinks',{'id' : node_id})
        backlinks = s['backlinks']

        if backlinks:
            self.menu = NodeBrowserMenu(
                project=current_project,
                nodes=backlinks)

            show_panel(
                self.view.window(), 
                self.menu.display_menu, 
                self.open_the_file)

#TODO fix, returns all nodes
class ForwardlinksBrowser(NodeBrowserCommand):

    def run(self, view):
        node_id = get_node_id(self.view)
        s = urtext_get('forward-links',{'id' : node_id})

        forward_links = s['forward-links']
        self.menu = NodeBrowserMenu(
            project=current_project,
            nodes=forward_links,
            )
        show_panel(
            self.view.window(), 
            self.menu.display_menu, 
            self.open_the_file)

class AllProjectsNodeBrowser(NodeBrowserCommand):
    
    def run(self, view):
        self.menu = NodeBrowserMenu(project=None)
        show_panel(
            self.view.window(), 
            self.menu.display_menu, 
            self.open_the_file)
#REWRITE
class FullTextSearchCommand(UrtextTextCommand):

    def run(self, view):
        self.view.window().show_input_panel(
            'search terms',
            '',
            self.show_results,
            None,
            None
            )
    
    def show_results(self, string):
        s = urtext_get('search', {'string':string})
        
        self.results_view = self.window.new_file()
        self.results_view.set_scratch(True)
        self.results_view.set_syntax_file('sublime_urtext.sublime-syntax')

        while self.results_view.is_loading():
            time.sleep(0.1)

        final_results = s['results']            
        for item in final_results:
            self.results_view.run_command("append", {"characters": item +'\n'})

def size_to_groups(groups, view):
    panel_size = 1 / groups
    cols = [0]
    cells = [[0, 0, 1, 1]]
    for index in range(1, groups):
        cols.append(cols[index - 1] + panel_size)
        cells.append([index, 0, index + 1, 1])
    cols.append(1)
    view.window().set_layout({"cols": cols, "rows": [0, 1], "cells": cells})
    # view.window().set_layout({"cols": cols, "rows": [0, 1], "cells": cells})

def size_to_thirds(groups,view):
    # https://forum.sublimetext.com/t/set-layout-reference/5713
    # {'cells': [[0, 0, 1, 1], [1, 0, 2, 1]], 'rows': [0, 1], 'cols': [0, 0.5, 1]}
    view.window().set_layout({"cols": [0.0, 0.3333, 1], "rows": [0, 1], "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]})

# view.window().set_layout({
#     "cols": [0.0, 0.3333, 0.66666, 1], 
#     "rows": [0, 0.33333, 0.6666, 1], 
#     "cells": [
#         [0, 0, 1, 1], [0,1,1,2], [1,1,2,2], 
#         [1, 0, 2, 1], [2,0,3,1], [2,1,3,2],
#         [0, 2, 1, 3], [1,2,2,3], [2,2,3,3],
#         ]
#     })

#DONE
class InsertNodeCommand(sublime_plugin.TextCommand):
    def run(self, view):
        add_inline_node(self.view)

#DONE
class InsertNodeSingleLineCommand(sublime_plugin.TextCommand):
    def run(self, view):
        add_inline_node(self.view, trailing_id=True, include_timestamp=False)    

#DONE
def add_inline_node(view, 
    trailing_id=False,
    include_timestamp=True,
    locate_inside=True):
       
    region = view.sel()[0]
    selection = view.substr(region)
    s = urtext_get('add-inline-node', {
        'contents': selection,
        'trailing_id' : str(trailing_id),
        'include_timestamp' : str(include_timestamp)
        })
    
    view.run_command("insert_snippet", {"contents": s['contents']})  # (whitespace)
    if locate_inside:
        view.sel().clear()
        new_cursor_position = sublime.Region(region.a + 3, region.a + 3 ) 
        view.sel().add(new_cursor_position) 
    return s['id']

#DONE
class RenameFileCommand(UrtextTextCommand):

    def run(self, view):
        old_filename = self.view.file_name()
        s = urtext_get('rename-file', { 'old_filename' : old_filename})
        self.view.retarget(s['new-filename'])

class NodeInfo():

    def __init__(self, node):    
        self.title = node['title']
        self.date = node['date']
        self.filename = node['filename']
        self.position = int(node['position'])
        self.node_id = node['id']
        self.project_title = node['project_title']

def make_node_menu(project='', nodes=''):

    s = urtext_get('nodes', { 'project' : project})
    menu = []
    for node in s['nodes']:
        if nodes == '' or node['id'] in nodes:
            menu.append(NodeInfo(node))
    return menu
    
 
def make_display_menu(menu):
    display_menu = []
    for item in menu:
        item.position = int(item.position)
        new_item = [
            item.title,
            item.project_title + ' - ' + item.date,      
        ]
        display_menu.append(new_item)
    return display_menu

#DONE
class LinkToNodeCommand(UrtextTextCommand):

    def run(self, edit):
        self.menu = NodeBrowserMenu(project=os.path.dirname(self.view.file_name()))
        show_panel(self.view.window(), self.menu.display_menu, self.link_to_the_node)

    def link_to_the_node(self, selected_option):
        selected_item = self.menu.full_menu[selected_option]
        s = urtext_get('get-link-to-node', {
                'node_id' : selected_item.node_id,    
                'project' : os.path.dirname(self.view.file_name())
            })
        self.view.run_command("insert", {"characters": s['link']})

#DONE
class CopyLinkToHereCommand(UrtextTextCommand):
    """
    Copy a link to the node containing the cursor to the clipboard.
    Does not include project title.
    """
    
    def run(self, edit):

        if not self.window:
            self.window = self.view.window()
        s = urtext_get('get-link-to-node', {
            'node_id' : get_node_id(self.window.active_view()),
            'project' :  os.path.dirname(self.view.file_name()),
            })
        sublime.set_clipboard(s['link'])        

        self.view.show_popup(s['link'] + '\ncopied to the clipboard', 
            max_width=1800, 
            max_height=1000 
            )
#DONE
class CopyLinkToHereWithProjectCommand(UrtextTextCommand):
    """
    Copy a link to the node containing the cursor to the clipboard.
    Does not include project title.
    """
    def run(self, edit):
        s = urtext_get('get-link-to-node', {
            'node_id' : get_node_id(self.window.active_view()),
            'project' :  os.path.dirname(self.view.file_name()),
            'include_project' : 'True'
            })
        sublime.set_clipboard(s['link'])        

        self.view.show_popup(s['link'] + '\ncopied to the clipboard', 
            max_width=1800, 
            max_height=1000 
            )

def get_contents(view):
    if view != None:
        contents = view.substr(sublime.Region(0, view.size()))
        return contents
    return None

#DONE
class NewNodeCommand(UrtextTextCommand):

    def run(self, view):
        s = urtext_get('new-node')
        new_view = self.view.window().open_file(s['filename'])
#DONE
class InsertLinkToNewNodeCommand(UrtextTextCommand):
    
    def run(self, view):
        s = urtext_get('new-node')
        self.view.run_command("insert", {"characters":'| >' + s['id']})

#DONE
class NewProjectCommand(UrtextTextCommand):

    def run(self, view):
        urtext_get('new-project',{'path':get_path(self.view)})
        new_view = self.window.new_file()
        new_view.set_scratch(True)
        new_view.close()
#DONE    
class DeleteThisNodeCommand(UrtextTextCommand):

    def run(self, view):
        file_name = self.view.file_name()
        if self.view.is_dirty():
            self.view.set_scratch(True)
        self.view.window().run_command('close_file')
        urtext_get('delete-file', {'filename' : file_name})
#DONE
class InsertTimestampCommand(UrtextTextCommand):

    def run(self, edit):
        s = urtext_get('timestamp')
        datestamp = s['timestamp']

        for s in self.view.sel():
            if s.empty():
                self.view.insert(edit, s.a, datestamp)
            else:
                self.view.replace(edit, s, datestamp)
#DONE
class ConsolidateMetadataCommand(UrtextTextCommand):

    def run(self, edit):
        self.view.run_command('save')  # TODO insert notification
        node_id = get_node_id(self.view)
        if node_id:
            s = urtext_get('consolidate-metadata', {
                'node-id' : node_id,
                'one_line' : 'True'
                }) 
            return True    
        print('No Urtext node or no Urtext node with ID found here.')
        return False
#DONE
class InsertDynamicNodeDefinitionCommand(UrtextTextCommand):

    def run(self, edit):
        now = datetime.datetime.now()
        node_id = add_inline_node(
            self.view, 
            include_timestamp=False,
            locate_inside=False)

        # TODO This should possibly be moved into Urtext as a utility method.
        position = self.view.sel()[0].a
        content = '\n\n[[ ID(>' + node_id + ')\n\n ]]'
        
        for s in self.view.sel():
            if s.empty():
                self.view.insert(edit, s.a, content)
            else:
                view.replace(edit, s, content)

        self.view.sel().clear()
        new_cursor_position = sublime.Region(position + 12, position + 12) 
        self.view.sel().add(new_cursor_position) 
#DONE
class TagFromOtherNodeCommand(UrtextTextCommand):

    def run(self, edit):
        self.view.run_command('save')
        s = urtext_get('tag-from-other', {
            'line': self.view.substr(self.view.line(self.view.sel()[0])),
            'column': self.view.sel()[0].a,
            })        
#DONE
class ReIndexFilesCommand(UrtextTextCommand):
    
    def run(self, edit):
        s = urtext_get('reindex',{'project':get_path(self.view)})
        renamed_files = s['renamed-files']
        for view in self.view.window().views():
            if view.file_name() == None:
                continue
            if os.path.basename(view.file_name()) in renamed_files:
                view.retarget(renamed_files[os.path.basename(view.file_name())])
#DONE
class AddNodeIdCommand(UrtextTextCommand):

    def run(self, edit):
        s = urtext_get('next-id', {'project':get_path(self.view)})
        self.view.run_command("insert_snippet",
                              {"contents": "id::" + s['node_id']})

#REWRITE
class OpenUrtextLogCommand(UrtextTextCommand):
    def run(self, edit):
        s = urtext_get('get-log-node',{'project':get_path(self.view)} )
        if s['log_id'] != 'None':

            open_urtext_node(self.view, s['filename'], s['log_id'], s['position'])

            def go_to_end(view):
                if not view.is_loading():
                    view.show_at_center(sublime.Region(view.size()))
                    view.sel().add(sublime.Region(view.size()))
                    view.show_at_center(sublime.Region(view.size()))
                else:
                    sublime.set_timeout(lambda: go_to_end(view), 10)

            go_to_end(self.view)
#DONE
class CompactNodeCommand(UrtextTextCommand):

    def run(self, edit):
    
        region = self.view.sel()[0]
        selection = self.view.substr(region)
        line = self.view.line(region) # get full line
        next_line_down = line.b
        s = urtext_get('compact-node',{
            'project':get_path(self.view), 
            'selection' : selection
            })

        self.view.sel().clear()
        self.view.sel().add(next_line_down) 
        self.view.run_command("insert_snippet",{"contents": '\n'+s['new_node_contents']})

        new_cursor_position = sublime.Region(next_line_down + 3, next_line_down + 3) 
        self.view.sel().clear()
        self.view.sel().add(new_cursor_position) 
        self.view.erase(edit, region)

#DONE
class PopNodeCommand(UrtextTextCommand):

    def run(self, edit):
        filename = self.view.file_name()
        position = self.view.sel()[0].a
        s = urtext_get('pop-node', {
            'project':get_path(self.view), 
            'filename' : filename,
            'position' :position,
            })
#DONE
class PullNodeCommand(UrtextTextCommand):

    def run(self, edit):
        filename = self.view.file_name()
        position = self.view.sel()[0].a
        full_line = self.view.substr(self.view.line(self.view.sel()[0]))
        s = urtext_get('pull-node', {
            'project':get_path(self.view), 
            'filename' : filename,
            'position' :position,
            'full-line' : full_line,
            })
#DONE
class RandomNodeCommand(UrtextTextCommand):

    def run(self, edit):
        s = urtext_get('random-node', {'project':get_path(self.view)})
        open_urtext_node(self.view, s['filename'], s['node_id'])

# ADDED
class KeywordsCommand(UrtextTextCommand):
    def run(self, edit):
        window = self.view.window()
        s = urtext_get('keywords',  {'project':get_path(self.view)})
        keyphrases = list(s['keyphrases'].keys())
        self.chosen_keyphrase = ''

        def multiple_selections(selection):
            open_urtext_node(self.view, 
                self.second_menu.full_menu[selection].filename,
                self.second_menu.full_menu[selection].node_id,
                position=self.second_menu.full_menu[selection].position,
                highlight=self.chosen_keyphrase
                )

        def result(i):
            self.chosen_keyphrase = keyphrases[i]
            if len(s['keyphrases'][self.chosen_keyphrase]) == 1:
                node_id =s['keyphrases'][keyphrases[i]][0]
                open_urtext_node(
                    self.view,     
                    s['nodes'][node_id]['filename'],
                    node_id,
                    position=s['nodes'][node_id]['position'],
                    highlight=self.chosen_keyphrase
                    )
            else:
                self.second_menu = NodeBrowserMenu(
                    project=get_path(self.view), 
                    nodes=s['keyphrases'][self.chosen_keyphrase])

                show_panel(
                    window, 
                    self.second_menu.display_menu, 
                    multiple_selections)

        window.show_quick_panel(keyphrases, result)


#DONE
class ToggleTraverse(UrtextTextCommand):

    def run(self, view):

        # determine whether then view already has traverse settings attached
        # if already on, turn it off
        if self.view.settings().has('traverse'):
            if self.view.settings().get('traverse') == 'true':
                self.view.settings().set('traverse', 'false')
                self.view.set_status('traverse', 'Traverse: Off')
                groups = self.view.window().num_groups()
                groups -= 1
                if groups == 0:
                    groups = 1
                size_to_groups(groups, self.view)
                self.view.settings().set("word_wrap", True)
                return

        # otherwise, if 'traverse' is not in settings or it's 'false',
        # turn it on.
        self.view.settings().set('traverse', 'true')
        self.view.set_status('traverse', 'Traverse: On')

        # Add another group to the left if needed
        groups = self.view.window().num_groups() # 1-indexed
        active_group = self.view.window().active_group()  # 0-indexed
        if active_group + 1 == groups:
            groups += 1
        #size_to_groups(groups, self.view)
        size_to_thirds(groups,self.view)
        self.view.settings().set("word_wrap", False)


        # move any other open tabs to rightmost pane.
        views = self.view.window().views_in_group(active_group)
        index = 0
        for view in views:
            if view != self.view:
                self.view.window().set_view_index(
                    view,
                    groups - 1,  # 0-indexed from 1-indexed value
                    index)
                index += 1

        self.view.window().focus_group(active_group)

class ToIcs(UrtextTextCommand):

    def run(self):
         _UrtextProjectList.current_project.export_to_ics()

#DONE
class TraverseFileTree(EventListener):

    def on_selection_modified(self, view):
        
        # give this view a name since we have so many to keep track of
        called_from_view = view 
        if called_from_view.name() == 'urtext_history':
            return
        #
        # TODO:
        # Add a failsafe in case the user has closed the next group to the left
        # but traverse is still on.
        #
        if called_from_view.window() == None:
            return
        if called_from_view.settings().get('traverse') == 'false':
            return

        # 1-indexed number of current groups ("group" = window division)
        self.groups = called_from_view.window().num_groups()        

        # 0-indexed number of the group with the tree view
        # Tree group is always made to be the view this was called from.
        self.tree_group = called_from_view.window().active_group() 
        if called_from_view.window().active_group() + 1 == self.groups:
            # if the called_from_group is rightmost, return
            # OR what if checking to see if the filenames are the same?
            return

        # 0-indexed number of the group with the content 
        # (may not yet exist)
        self.content_group = self.tree_group + 1        
        
        # TAB of the content (right) view. ("sheet" = tab)        
        self.content_tab = called_from_view.window().active_sheet_in_group(self.tree_group)

        
        # the contents of the content tab. 
        contents = get_contents(self.content_tab.view())

        """ 
        Scroll to a given position of the content 
        and then return focus to the tree view.
        """
        def move_to_location(moved_view, 
            position, 
            tree_view):
            
            if not moved_view.is_loading():

                # focus on the window division with the content
                moved_view.window().focus_group(self.content_group)

                # show the content tab with the given position as center
                self.content_tab.view().show_at_center(position)

                # Make this the selected spot and set word wrap
                moved_view.sel().clear()
                moved_view.sel().add(position)
                moved_view.settings().set("word_wrap", "auto")

                # refocus the tree (left) view
                self.return_to_left(moved_view, tree_view)

            else:
                sublime.set_timeout(lambda: move_to_location(moved_view, position),10)

        """ Only if Traverse is on for this group (window division) """

        if called_from_view.settings().get('traverse') == 'true':

            # the tree view is always the view that was modified.
            # assign it a name, get its filename and window

            this_file = called_from_view.file_name()
            
            if not this_file:
                return

            tree_view = called_from_view
            window = called_from_view.window()

            # Get the current line and find links
            full_line = view.substr(view.line(view.sel()[0]))
            links = re.findall('>' + node_id_regex, full_line)

            # if there are no links on this line:
            if len(links) == 0:  
                return

            # get all the filenames corresponding to the links
            filenames = []
            for link in links:
                s = urtext_get('filename-from-link', {'link' : link[1:]})
                filename = s['filename']
                if filename:
                    filenames.append((s['filename'],s['position']))

            if len(filenames) > 0:  
                # and link[1:] in _UrtextProjectList.current_project.nodes:
                filename = filenames[0][0]
                position = filenames[0][1]
                
                """ If the tree is linking to another part of its own file """
                if filename == os.path.basename(this_file):
                    
                    instances = self.find_filename_in_window(filename, window)

                    # Only allow two total instances of this file; 
                    # one to navigate, one to edit
                    if len(instances) < 2:
                        window.run_command("clone_file")
                        duplicate_file_view = self.find_filename_in_window(filename, window)[1]

                    if len(instances) >= 2:
                        duplicate_file_view = instances[1]
                    
                    """ If the duplicate view is in the content group """
                    if duplicate_file_view in window.views_in_group(self.content_group):
                        window.focus_view(duplicate_file_view)
                        duplicate_file_view.show_at_center(position)
                        duplicate_file_view.sel().clear()
                        duplicate_file_view.sel().add(position)
                        
                        self.return_to_left(duplicate_file_view, tree_view)
                        duplicate_file_view.settings().set('traverse', 'false')
                        return

                    """ If the duplicate view is in the tree group """
                    if duplicate_file_view in window.views_in_group(self.tree_group):
                        window.focus_group(self.tree_group)
                        duplicate_file_view.settings().set('traverse', 'false')  # this is for the cloned view
                        window.set_view_index(duplicate_file_view, self.content_group, 0)
                        duplicate_file_view.show_at_center(position)
                        window.focus_view(tree_view)
                        window.focus_group(self.tree_group)
                        self.restore_traverse(view, tree_view)
                        return

                else:
                    """ The tree is linking to another file """
                    window.focus_group(self.content_group)
                    file_view = window.open_file( filename,sublime.TRANSIENT)
                    file_view.show_at_center(position)
                    file_view.sel().clear()
                    file_view.sel().add(position)
                    window.focus_group(self.tree_group)
                    self.return_to_left(file_view, tree_view)

    def find_filename_in_window(self, filename, window):
        instances = []
        for view in window.views():
            if view.file_name() == filename:
                instances.append(view)
        return instances

    def restore_traverse(self, wait_view, traverse_view):
        if not wait_view.is_loading():
            traverse_view.settings().set('traverse', 'true')
        else:
            sublime.set_timeout(
                lambda: self.return_to_left(wait_view, traverse_view), 10)
            return

    """ 
    Return to the left (tree) view,
    after waiting for another view to finish loading.
    """

    def return_to_left(self, 
        wait_view, 
        return_view):
        
        if not wait_view.window():
            return

        if not wait_view.is_loading():
            wait_view.window().focus_view(return_view)
            wait_view.window().focus_group(self.tree_group)
        
        else:
            sublime.set_timeout(lambda: self.return_to_left(wait_view, return_view), 10)

"""
Utility functions
"""
def open_urtext_node(
    view, 
    filename, 
    node_id, 
    project=None,
    position=0, 
    highlight=''):
    
    file_view = view.window().find_open_file(filename)
    if not file_view:
        file_view = view.window().open_file(filename)
    view.window().focus_view(file_view)
    center_node(file_view, position)

    def highlight_callback():
        if not file_view.is_loading():
            highlight_phrase(file_view, highlight)
        else:
            sublime.set_timeout(lambda: highlight_callback(), 30) 

    if highlight:
        highlight_callback()


    return file_view
    """
    Note we do not involve this function with navigation, since it is
    use for purposes including forward/backward navigation and shouldn't
    duplicate/override any of the operations of the methods that call it.
    """

def center_node(new_view, position): 
        if not new_view.is_loading():
            new_view.sel().clear()
            # this has to be called both before and after:
            new_view.show_at_center(position)
            new_view.sel().add(sublime.Region(position, position))
            # this has to be called both before and after:
            new_view.show(sublime.Region(position, position))
            new_view.show_at_center(position)
        else:
            # NOTE: if node does not center in the view, adjust the delay higher.
            sublime.set_timeout(lambda: center_node(new_view, position), 30) 



def get_path(view):  ## makes the path persist as much as possible ##

    if view.file_name():
        return os.path.dirname(view.file_name())
    if view.window():
        return get_path_from_window(view.window())
    return None

def get_path_from_window(window):

    folders = window.folders()
    if folders:
        return folders[0]
    if window.project_data():
        return window.project_data()['folders'][0]['path']
    return None

def refresh_open_file(future, view):
    changed_files = future.result()
    open_files = view.window().views()
    for filename in open_files:
        if os.path.basename(filename) in changed_files:
            view.run_command('revert') # undocumented

def open_external_file(filepath):

    if sublime.platform() == "osx":
        subprocess.Popen(('open', filepath))
    elif sublime.platform() == "windows":
        os.startfile(filepath)
    elif sublime.platform() == "linux":
        subprocess.Popen(('xdg-open', filepath))

def get_node_id(view):
    if view.file_name():
        filename = os.path.basename(view.file_name())
        position = view.sel()[0].a
        s = urtext_get('id-from-position', { 'filename' : filename, 'position' : position})
        return s['id']

def highlight_phrase(view, phrase):
    regions = view.find_all(phrase, flags=sublime.IGNORECASE)
    view.add_regions(
        'urtext_highlight', 
        regions, 
        'urtext', 
        )

class UrtextCompletions(EventListener):

    def on_query_completions(self, view, prefix, locations):
        #s = urtext_get('completions',{'project':get_path(view)} )
        s = urtext_get('keywords',{'project':get_path(view)} )
        subl_completions = []
        proj_completions = s['keyphrases']
        for c in proj_completions:
            t = c.split('::')
            if len(t) > 1:
                subl_completions.append([t[1]+'\t'+c, c])
        # title_completions = s['titles']
        # for t in title_completions:
        #     subl_completions.append([t[0],t[1]])
        # completions = (subl_completions, sublime.INHIBIT_WORD_COMPLETIONS)
       
        return subl_completions

class UrtextSaveListener(EventListener):

    def __init__(self):   
        pass
        #self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
     
    def on_post_save_async(self, view):
        s = urtext_get('modified', {'filename' : view.file_name() })

        # if s['is_async'] == 'True':
        #     if result:
        #         renamed_file = result.result()
        #         if renamed_file and renamed_file != filename:
        #             view.set_scratch(True) # already saved
        #             view.close()
        #             new_view = view.window().open_file(renamed_file)
        #         else:
        #             self.executor.submit(refresh_open_file, filename, view)
        # else:
        #     if result and result != filename:
        #         window = view.window()
        #         view.set_scratch(True) # already saved
        #         view.close()
        #         new_view = window.open_file(result)
        #     else:
        #         self.executor.submit(refresh_open_file, filename, view)
        
        #always take a snapshot manually on save
        #take_snapshot(view, self._UrtextProjectList.current_project)
            

# class KeepPosition(EventListener):

#     @refresh_project_event_listener
#     def on_modified(self, view):
#         if not view:
#             return

#         position = view.sel()
#         def restore_position(view, position):
#             if not view.is_loading():
#                 view.show(position)
#             else:
#                 sublime.set_timeout(lambda: restore_position(view, position), 10)

#         restore_position(view, position)

# class JumpToSource(EventListener):

#     @refresh_project_event_listener
#     def on_modified(self, view):
#         """
#         problematic -- this doesn't work if the view is dirty.

#         TODO: revise
#         For now, making available only if few is not dirty. However this should
#         still be usable in many cases.
#         """
#         if not view:
#             return
#         position = view.sel()[0].a
#         filename = view.file_name()
#         if filename:
#             destination_node = _UrtextProjectList.is_in_export(filename, position)
#             if destination_node:
#                 view.window().run_command('undo') # undo the manual change made to the view
#                 open_urtext_node(view, destination_node[0])
#                 center_node(view, destination_node[1])
