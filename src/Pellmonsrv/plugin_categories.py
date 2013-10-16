#! /usr/bin/python
# -*- coding: utf-8 -*-
"""
    Copyright (C) 2013  Anders Nylund

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from Pellmonsrv.yapsy.IPlugin import IPlugin

class protocols(IPlugin):
    """Plugins of this class read and write data"""
    def activate(self, conf):
        self.conf = conf
        IPlugin.activate(self)
        
    def getItem(self, item):
        pass
        
    def setItem(self, item, value):
        pass
        
    def getDbWithTags(self, tags):
        pass

