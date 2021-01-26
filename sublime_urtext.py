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
is_browsing_history = False
URL = 'http://127.0.0.1:5000/'
node_id_regex = r'\b[0-9,a-z]{3}\b'

def urtext_get(endpoint, values={}):
    try:
        data = urllib.parse.urlencode(values)
    except URLError:
        ('No Urtext project serving')
        return {'':''}
    data = data.encode('ascii') 
    r = urllib.request.urlopen(URL + endpoint, data)
    response = r.read().decode('utf-8')
    return json.loads(response)

class UrtextTextCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view
        self.window = view.window()

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

class UrtextHomeCommand(sublime_plugin.TextCommand):
    
    def run(self, view):
        s = urtext_get('home', {'project':get_path(self.view)})
        if 'filename' in s:
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])
class NavigateBackwardCommand(sublime_plugin.TextCommand):
    def run(self, view):
        s = urtext_get('nav-back')
        if s['nav_current'] != 'NONE':
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])
class NavigateForwardCommand(sublime_plugin.TextCommand):
    def run(self, view):
        s = urtext_get('nav-forward')
        if s['nav_current'] != 'NONE':
            open_urtext_node(self.view, s['filename'], s['nav_current'], s['position'])

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

def take_snapshot(view):
    if view and view.file_name():
        filename = os.path.basename(view.file_name())
        s = urtext_get('snapshot', {
            'project': os.path.dirname(view.file_name()),
            'filename':view.file_name(), 
            'contents':get_contents(view)})
        return s['success']
    return False  

class ToggleHistoryTraverse(UrtextTextCommand):
    """ Toggles history traversing on/off """
    def run(self, edit):
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
        #take_snapshot(self.view, self._UrtextProjectList.current_project)
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
        s = urtext_get('get-history', {
                'project' : os.path.dirname(filename),
                'filename' : filename,
            })
        
        new_history = json.loads(s['history'])
        if not new_history:
            return None
        ts_format =  s['timestamp-format']
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

        s = urtext_get('apply-patches', {
            'history' : json.dumps(self.history),
            'distance-back' : index
            })
        state = s['state']
        self.file_view.run_command("select_all")
        self.file_view.run_command("right_delete")
        for line in state.split('\n'):
            self.file_view.run_command("append", {"characters": line+ "\n" })

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

def size_to_thirds(groups,view):
    # https://forum.sublimetext.com/t/set-layout-reference/5713
    view.window().set_layout({"cols": [0.0, 0.3333, 1], "rows": [0, 1], "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]})

class InsertNodeCommand(sublime_plugin.TextCommand):
    def run(self, view):
        add_inline_node(self.view)

class InsertNodeSingleLineCommand(sublime_plugin.TextCommand):
    def run(self, view):
        add_inline_node(self.view, include_timestamp=False)    

def add_inline_node(view, 
    include_timestamp=True,
    locate_inside=True):
       
    region = view.sel()[0]
    selection = view.substr(region)
    s = urtext_get('add-inline-node', {
        'contents': selection,
        'include_timestamp' : str(include_timestamp)
        })
    
    view.run_command("insert_snippet", {"contents": s['contents']})  # (whitespace)
    if locate_inside:
        view.sel().clear()
        new_cursor_position = sublime.Region(region.a + 3, region.a + 3 ) 
        view.sel().add(new_cursor_position) 
    return s['id']

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
    if nodes == '':
        s = urtext_get('nodes', { 'project' : project})
        nodes = s['nodes']
    menu = []
    for node in nodes:
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

class NewNodeCommand(UrtextTextCommand):
    def run(self, view):
        s = urtext_get('new-node')
        new_view = self.view.window().open_file(s['filename'])
class InsertLinkToNewNodeCommand(UrtextTextCommand):
    
    def run(self, view):
        s = urtext_get('new-node')
        self.view.run_command("insert", {"characters":'| >' + s['id']})

class NewProjectCommand(UrtextTextCommand):
    def run(self, view):
        urtext_get('new-project',{'path':get_path(self.view)})
        new_view = self.window.new_file()
        new_view.set_scratch(True)
        new_view.close()
    
class DeleteThisNodeCommand(UrtextTextCommand):
    def run(self, view):
        file_name = self.view.file_name()
        if self.view.is_dirty():
            self.view.set_scratch(True)
        self.view.window().run_command('close_file')
        urtext_get('delete-file', {'filename' : file_name})

class InsertTimestampCommand(UrtextTextCommand):
    def run(self, edit):
        s = urtext_get('timestamp')
        datestamp = s['timestamp']
        for s in self.view.sel():
            if s.empty():
                self.view.insert(edit, s.a, datestamp)
            else:
                self.view.replace(edit, s, datestamp)

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

class TagFromOtherNodeCommand(UrtextTextCommand):
    def run(self, edit):
        self.view.run_command('save')
        s = urtext_get('tag-from-other', {
            'line': self.view.substr(self.view.line(self.view.sel()[0])),
            'column': self.view.sel()[0].a,
            })        
class ReIndexFilesCommand(UrtextTextCommand):
    
    def run(self, edit):
        s = urtext_get('reindex',{'project':get_path(self.view)})
        renamed_files = s['renamed-files']
        print(renamed_files)
        for view in self.view.window().views():
            if view.file_name() == None:
                continue
            if view.file_name() in renamed_files:
                view.retarget(renamed_files[view.file_name()])

class AddNodeIdCommand(UrtextTextCommand):
    def run(self, edit):
        s = urtext_get('next-id', {'project':get_path(self.view)})
        self.view.run_command("insert_snippet",
                              {"contents": "@" + s['node_id']})
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

class CompactNodeCommand(UrtextTextCommand):

    def run(self, edit):
        region = self.view.sel()[0]
        selection = self.view.substr(region)
        line_region = self.view.line(region) # get full line region
        line_contents = self.view.substr(line_region)
        s = urtext_get('compact-node',{
            'filename':self.view.file_name(),
            'position': self.view.sel()[0].a,
            'project':get_path(self.view), 
            'selection' : line_contents,
            })
        if s['replace']:
            self.view.erase(edit, line_region)
            self.view.run_command("insert_snippet",{"contents": s['contents']})
            region = self.view.sel()[0]
            self.view.sel().clear()
            self.view.sel().add(sublime.Region(region.a-5, region.b-5))
        else:
            next_line_down = line_region.b    
            self.view.sel().clear()
            self.view.sel().add(next_line_down) 
            self.view.run_command("insert_snippet",{"contents": '\n'+s['contents']})            
            new_cursor_position = sublime.Region(next_line_down + 3, next_line_down + 3) 
            self.view.sel().clear()
            self.view.sel().add(new_cursor_position) 

class PopNodeCommand(UrtextTextCommand):
    def run(self, edit):
        s = urtext_get('pop-node', {
            'project':get_path(self.view), 
            'filename' : self.view.file_name(),
            'position' : self.view.sel()[0].a,
            })
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
class RandomNodeCommand(UrtextTextCommand):
    def run(self, edit):
        s = urtext_get('random-node', {'project':get_path(self.view)})
        open_urtext_node(self.view, s['filename'], s['node_id'])

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
                nodes = [s['nodes'][nid] for nid in s['keyphrases'][self.chosen_keyphrase]]
                self.second_menu = NodeBrowserMenu(
                    project=get_path(self.view), 
                    nodes=nodes)
                show_panel(
                    window, 
                    self.second_menu.display_menu, 
                    multiple_selections)
        window.show_quick_panel(keyphrases, result)

# ADDED

class AssociateCommand(NodeBrowserCommand):

     def run(self, edit):
        position = self.view.sel()[0].a
        column = self.view.rowcol(position)[1]
        full_line = self.view.substr(self.view.line(self.view.sel()[0]))
        s = urtext_get('associate', {
            'project':get_path(self.view),
            'string' : full_line,
            'filename' : self.view.file_name(),
            'position' : self.view.sel()[0].a,
            })

        self.menu = NodeBrowserMenu(
                project=get_path(self.view), 
                nodes=s['nodes'])

        show_panel(
            self.view.window(), 
            self.menu.display_menu, 
            self.open_the_file)
       
     def open_the_file(self, selected_option):        
        selected_item = self.menu.full_menu[selected_option]
        s = urtext_get('nav', {'node' : selected_item.node_id })
        open_urtext_node(
            self.view, 
            selected_item.filename, 
            selected_item.node_id, 
            position=selected_item.position)

class ToIcs(UrtextTextCommand):
    def run(self):
         _UrtextProjectList.current_project.export_to_ics()


"""
Utility functions
"""

def get_path(view):
    """ 
    given a view or None, establishes the current path,
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

class UrtextSaveListener(EventListener):
    def __init__(self):   
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)     
        self.completions = []
        self.title_completions = []
    
    def on_post_save(self, view):
        self.executor.submit(self._urtext_save, view)

    def _urtext_save(self, view):
        filename = view.file_name()
        if not filename:
            return
        s = urtext_get('modified', {'filename' : filename })
        self.completions = s['completions']
        self.titles = s['titles']
        renamed_file = s['filename']
        if renamed_file and renamed_file != os.path.basename(filename):
            view.set_scratch(True) # already saved
            view.close()
            new_view = view.window().open_file(renamed_file)
        else:
            self.executor.submit(refresh_open_file, filename, view)
        
        take_snapshot(view)
        
    def on_query_completions(self, view, prefix, locations):
        subl_completions = []
        for c in self.completions:
            t = c.split('::')
            if len(t) > 1:
                subl_completions.append([t[1]+'\t'+c, c])
        for t in self.title_completions:
            subl_completions.append([t[0],t[1]])
        completions = (subl_completions, sublime.INHIBIT_WORD_COMPLETIONS)       
        return completions

    def on_deactivated(self, view):
        urtext_settings = sublime.load_settings('urtext.sublime-settings')
        if urtext_settings.get('save_on_focus_change'):
             self.executor.submit(self._urtext_save, view)
