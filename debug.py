import sublime
import sublime_plugin
from .sublime_urtext import urtext_get

class DebugCommand(sublime_plugin.TextCommand):

    def run(self, view):
        position = self.view.sel()[0].a
        s = urtext_get('log-node-meta', {'filename' : self.view.file_name(), 'position' : position})

class UrtextTurnOffThreadingCommand(sublime_plugin.TextCommand):

    def run(self, view):
        s=urtext_get('/async-off')
        print(s)
