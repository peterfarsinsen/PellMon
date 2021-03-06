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

import os.path
import cherrypy
from cherrypy.lib.static import serve_file, serve_fileobj
from cherrypy.process import plugins, servers
import ConfigParser
from mako.template import Template
from mako.lookup import TemplateLookup
from cherrypy.lib import caching
from gi.repository import Gio, GLib, GObject
import simplejson
import threading, Queue
from Pellmonweb import *
from time import time, mktime
import threading
import sys
from Pellmonweb import __file__ as webpath
import argparse
import pwd
import grp
import subprocess
from datetime import datetime

class DbusNotConnected(Exception):
    pass

class Dbus_handler:
    def __init__(self, bus='SESSION'):
        if bus=='SYSTEM':
            self.bustype=Gio.BusType.SYSTEM
        else:
            self.bustype=Gio.BusType.SESSION

    def setup(self):
        # Needed to be able to use threads with a glib main loop running
        GObject.threads_init()
        # A main loop is needed for dbus "name watching" to work
        main_loop = GObject.MainLoop()
        # The glib main loop gets along with the cherrypy main loop if run in it's own thread
        DBUSLOOPTHREAD = threading.Thread(name='glib_mainloop', target=main_loop.run)
        # This causes the dbus main loop thread to just die when the main thread exits
        DBUSLOOPTHREAD.setDaemon(True)
        # Start it here, thes must happen after the daemonizer double fork
        DBUSLOOPTHREAD.start()
        self.notify = None
        self.bus = Gio.bus_get_sync(self.bustype, None)
        Gio.bus_watch_name(
            self.bustype,
            'org.pellmon.int',
            Gio.DBusProxyFlags.NONE,
            self.dbus_connect,
            self.dbus_disconnect,
        )

    def dbus_connect(self, connection, name, owner):
        self.notify = Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            'org.pellmon.int',
            '/org/pellmon/int',
            'org.pellmon.int',
            None,
        )

    def dbus_disconnect(self, connection, name):
        if self.notify:
            self.notify = None

    def getItem(self, itm):
        if self.notify:
            return self.notify.GetItem('(s)',itm)
        else:
            raise DbusNotConnected("server not running")

    def setItem(self, item, value):
        if self.notify:
            return self.notify.SetItem('(ss)',item, value)
        else:
            raise DbusNotConnected("server not running")

    def getdb(self):
        if self.notify:
            return self.notify.GetDB()
        else:
            raise DbusNotConnected("server not running")

    def getDBwithTags(self, tags):
        if self.notify:
            return self.notify.GetDBwithTags('(as)',tags)
        else:
            raise DbusNotConnected("server not running")

    def getFullDB(self, tags):
        if self.notify:
            db = self.notify.GetFullDB('(as)', tags)
            return db
        else:
            raise DbusNotConnected("server not running")

    def getMenutags(self):
        if self.notify:
            return self.notify.getMenutags()
        else:
            raise DbusNotConnected("server not running")

class PellMonWeb:
    def __init__(self):
        self.logview = LogViewer(logfile)
        self.auth = AuthController(credentials)
        self.consumptionview = Consumption(polling, db)

    @cherrypy.expose
    def form1(self, **args):
        # The checkboxes are submitted with 'post'
        if cherrypy.request.method == "POST":
            # put the selection in session
            for key,val in polldata:
                # is this dataset checked?
                if args.has_key(val):
                    # if so, set it in the session
                    cherrypy.session[val] = 'yes'
                else:
                    cherrypy.session[val] = 'no'
        # redirect back after setting selection in session
        raise cherrypy.HTTPRedirect('/')

    @cherrypy.expose
    def autorefresh(self, **args):
        if cherrypy.request.method == "POST":
            if args.has_key('autorefresh') and args.get('autorefresh') == 'yes':
                cherrypy.session['autorefresh'] = 'yes'
            else:
                cherrypy.session['autorefresh'] = 'no'
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return simplejson.dumps(dict(enabled=cherrypy.session['autorefresh']))

    @cherrypy.expose
    def image(self, **args):
        if not polling:
            return None
        if len(colorsDict) == 0:
            return None
            
        try:
            timeChoice = args['timeChoice']
            timeChoice = timeChoices.index(timeChoice)
            cherrypy.session['timeChoice'] = timeChoice
        except:
            pass

        try:
            timeChoice = cherrypy.session['timeChoice']
            seconds=timeSeconds[timeChoice]
        except:
            seconds=timeSeconds[0]

        # Set time offset with ?time=xx 
        try:
            time = int(args['time'])
            # And save it in the session
            cherrypy.session['time'] = str(time)
        except:
            try:
                time = int(cherrypy.session['time'])
            except:
                time = 0


        try:
            direction = args['direction']
            if direction == 'left':
                time=time+seconds
            elif direction == 'right':
                time=time-seconds
                if time<0:
                    time=0
            cherrypy.session['time']=str(time)
        except:
            pass

        try:
            graphWidth = args.get('maxWidth')
            test = int(graphWidth) # should be int
        except:
            graphWidth = '440' # Default bootstrap 3 grid size

        graphTimeStart=str(seconds + time)
        graphTimeEnd=str(time)

        #Build the command string to make a graph from the database
        graph_file='-'
        if int(graphWidth)>500:
            rightaxis = '--right-axis 1:0'
        else:
            rightaxis = ''
        RrdGraphString1 = "rrdtool graph "+ graph_file + ' --disable-rrdtool-tag' +\
            " --lower-limit 0 %s --full-size-mode --width "%rightaxis + graphWidth + \
            " --height 400 --end now-" + graphTimeEnd + "s --start now-" + graphTimeStart + "s " + \
            "DEF:tickmark=%s:_logtick:AVERAGE TICK:tickmark#E7E7E7:1.0 "%db
        for key,value in polldata:
            if cherrypy.session.get(value)!='no' and colorsDict.has_key(key):
                RrdGraphString1=RrdGraphString1+"DEF:%s="%value+db+":%s:AVERAGE LINE1:%s%s:\"%s\" "% (ds_names[key], value, colorsDict[key], value)
        cmd = subprocess.Popen(RrdGraphString1, shell=True, stdout=subprocess.PIPE)
        cmd.wait()
        cherrypy.response.headers['Pragma'] = 'no-cache'
        return serve_fileobj(cmd.stdout)

    @cherrypy.expose
    def silolevel(self, **args):
        if not polling:
             return None
        try:
            reset_level=dbus.getItem('silo_reset_level')
            reset_time=dbus.getItem('silo_reset_time')
            reset_time = datetime.strptime(reset_time,'%d/%m/%y %H:%M')
            reset_time = mktime(reset_time.timetuple())
        except:
            return None
            
        if not cherrypy.request.params.get('maxWidth'):
            maxWidth = '440'; # Default bootstrap 3 grid size
        else:
            maxWidth = cherrypy.request.params.get('maxWidth')
        now=int(time())
        start=int(reset_time)
        RrdGraphString1=  "rrdtool graph - --lower-limit 0 --disable-rrdtool-tag --full-size-mode --width %s --right-axis 1:0 --right-axis-format %%1.1lf --height 400 --end %u --start %u "%(maxWidth, now,start)   
        RrdGraphString1+=" DEF:a=%s:feeder_time:AVERAGE DEF:b=%s:feeder_capacity:AVERAGE"%(db,db)
        RrdGraphString1+=" CDEF:t=a,POP,TIME CDEF:tt=PREV\(t\) CDEF:i=t,tt,-"
        #RrdGraphString1+=" CDEF:a1=t,%u,GT,tt,%u,LE,%s,0,IF,0,IF"%(start,start,reset_level)
        #RrdGraphString1+=" CDEF:a2=t,%u,GT,tt,%u,LE,3000,0,IF,0,IF"%(start+864000*7,start+864000*7)
        #RrdGraphString1+=" CDEF:s1=t,%u,GT,tt,%u,LE,%s,0,IF,0,IF"%(start, start, reset_level)
        RrdGraphString1+=" CDEF:s1=t,POP,COUNT,1,EQ,%s,0,IF"%reset_level
        RrdGraphString1+=" CDEF:s=a,b,*,360000,/,i,*" 
        RrdGraphString1+=" CDEF:fs=s,UN,0,s,IF" 
        RrdGraphString1+=" CDEF:c=s1,0,EQ,PREV,UN,0,PREV,IF,fs,-,s1,IF AREA:c#d6e4e9"
        print RrdGraphString1
        cmd = subprocess.Popen(RrdGraphString1, shell=True, stdout=subprocess.PIPE)
        cmd.wait()
        cherrypy.response.headers['Pragma'] = 'no-cache'
        return serve_fileobj(cmd.stdout)

    @cherrypy.expose
    def consumption(self, **args):
        if not polling:
             return None
        if consumption_graph:
            if not cherrypy.request.params.get('maxWidth'):
                maxWidth = '440'; # Default bootstrap 3 grid size
            else:
                maxWidth = cherrypy.request.params.get('maxWidth')
            now = int(time())
            align = now/3600*3600
            RrdGraphString = make_barchart_string(db, now, align, 3600, 24, '-', maxWidth, '24h consumption', 'kg/h')
            cmd = subprocess.Popen(RrdGraphString, shell=True, stdout=subprocess.PIPE)
            cmd.wait()
            cherrypy.response.headers['Pragma'] = 'no-cache'
            return serve_fileobj(cmd.stdout)

    @cherrypy.expose
    @require() #requires valid login
    def getparam(self, param):
        parameterlist=dbus.getdb()
        if cherrypy.request.method == "GET":
            if param in(parameterlist):
                try:
                    result = dbus.getItem(param)
                except:
                    result = 'error'
            else: result = 'not found'
            cherrypy.response.headers['Content-Type'] = 'application/json'
            return simplejson.dumps(dict(param=param, value=result))

    @cherrypy.expose
    @require() #requires valid login
    def setparam(self, param, data=None):
        parameterlist=dbus.getdb()
        if cherrypy.request.method == "POST":
            if param in(parameterlist):
                try:
                    result = dbus.setItem(param, data)
                except:
                    result = 'error'
            else: result = 'not found'
            cherrypy.response.headers['Content-Type'] = 'application/json'
            return simplejson.dumps(dict(param=param, value=result))

    @cherrypy.expose
    @require() #requires valid login
    def parameters(self, t1='', t2='', t3='', t4='', **args):
        # Get list of data/parameters
        try:
            level=cherrypy.session['level']
        except:
            cherrypy.session['level'] = 'Basic'
        level=cherrypy.session['level']
        try:
            parameterlist = dbus.getFullDB([level,t1,t2,t3,t4])
            # Set up a queue and start a thread to read all items to the queue, the parameter view will empty the queue bye calling /getparams/
            paramQueue = Queue.Queue(300)
            # Store the queue in the session
            cherrypy.session['paramReaderQueue'] = paramQueue
            ht = threading.Thread(target=parameterReader, args=(paramQueue,))
            ht.start()
            values=['']*len(parameterlist)
            params={}
            paramlist=[]
            datalist=[]
            commandlist=[]
            for item in parameterlist:
                if item['type'] == 'R':
                    datalist.append(item)
                if item['type'] == 'R/W':
                    paramlist.append(item)
                if item['type'] == 'W':
                    commandlist.append(item)
                try:
                    a = item['longname']
                except:
                    item['longname'] = item['name']
                try:
                    a = item['unit']
                except:
                    item['unit'] = ''
                try:
                    a = item['description']
                except:
                    item['description'] = ''

                params[item['name']] = ' '
                if args.has_key(item['name']):
                    if cherrypy.request.method == "POST":
                        # set parameter
                        try:
                            values[parameterlist.index(item['name'])]=dbus.setItem(item['name'], args[item['name']][1])
                        except:
                            values[parameterlist.index(item['name'])]='error'
                    else:
                        # get parameter
                        try:
                            values[parameterlist.index(item['name'])]=dbus.getItem(item['name'])
                        except:
                            values[parameterlist.index(item['name'])]='error'
            tmpl = lookup.get_template("parameters.html")
            tags = dbus.getMenutags()
            return tmpl.render(username=cherrypy.session.get('_cp_username'), data = datalist, params=paramlist, commands=commandlist, values=values, level=level, heading=t1, tags=tags)
        except DbusNotConnected:
            return "Pellmonsrv not running?"

    # Empty the item/value queue, call several times until all data is retrieved
    @cherrypy.expose
    @require() #requires valid login
    def getparams(self):
        parameterlist=dbus.getdb()
        paramReaderQueue = cherrypy.session.get('paramReaderQueue')
        params={}
        if paramReaderQueue:
            while True:
                try:
                    param,value = paramReaderQueue.get_nowait()
                    if param=='**end**':
                        # remove the queue when all items read
                        del cherrypy.session['paramReaderQueue']
                        break
                    params[param]=value
                except:
                    # queue is empty, send what's read so far
                    break
            cherrypy.response.headers['Content-Type'] = 'application/json'
            return simplejson.dumps(params)

    @cherrypy.expose
    @require() #requires valid login
    def setlevel(self, level='Basic'):
        cherrypy.session['level']=level
        # redirect back after setting selection in session
        raise cherrypy.HTTPRedirect(cherrypy.request.headers['Referer'])

    @cherrypy.expose
    def graphconf(self):
        checkboxes=[]
        empty=True
        for key, val in polldata:
            if colorsDict.has_key(key):
                if cherrypy.session.get(val) in ['yes', None]:
                    checkboxes.append((val,True))
                else:
                    checkboxes.append((val,''))
        tmpl = lookup.get_template("graphconf.html")
        return tmpl.render(checkboxes=checkboxes, empty=False)

    @cherrypy.expose
    def index(self, **args):
        autorefresh = cherrypy.session.get('autorefresh')=='yes'
        empty=True
        for key, val in polldata:
            if colorsDict.has_key(key):
                if cherrypy.session.get(val)=='yes':
                    empty=False
        tmpl = lookup.get_template("index.html")
        return tmpl.render(username=cherrypy.session.get('_cp_username'), empty=False, autorefresh=autorefresh, timeChoices=timeChoices, timeNames=timeNames, timeChoice=cherrypy.session.get('timeChoice'))

def parameterReader(q):
    parameterlist=dbus.getdb()
    for item in parameterlist:
        try:
            value = dbus.getItem(item)
        except:
            value='error'
        q.put((item,value))
    q.put(('**end**','**end**'))


HERE = os.path.dirname(webpath)
MEDIA_DIR = os.path.join(HERE, 'media')
FAVICON = os.path.join(MEDIA_DIR, 'favicon.ico')

#Look for temlates in this directory
lookup = TemplateLookup(directories=[os.path.join(HERE, 'html')])

parser = ConfigParser.ConfigParser()
config_file = 'pellmon.conf'

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(prog='pellmonweb')
    argparser.add_argument('-D', '--DAEMONIZE', action='store_true', help='Run as daemon')
    argparser.add_argument('-P', '--PIDFILE', default='/tmp/pellmonweb.pid', help='Full path to pidfile')
    argparser.add_argument('-U', '--USER', help='Run as USER')
    argparser.add_argument('-G', '--GROUP', default='nogroup', help='Run as GROUP')
    argparser.add_argument('-C', '--CONFIG', default='pellmon.conf', help='Full path to config file')
    argparser.add_argument('-d', '--DBUS', default='SESSION', choices=['SESSION', 'SYSTEM'], help='which bus to use, SESSION is default')
    args = argparser.parse_args()

    dbus = Dbus_handler(args.DBUS)

    # The dbus main_loop thread can't be started before double fork to daemon, the
    # daemonizer plugin has priority 65 so it's executed before dbus_handler.setup
    cherrypy.engine.subscribe('start', dbus.setup, 90)

    engine = cherrypy.engine

    # Only daemonize if asked to.
#    if daemonize:
    if args.DAEMONIZE:
        # Don't print anything to stdout/sterr.
        cherrypy.config.update({'log.screen': False})
        plugins.Daemonizer(engine).subscribe()
    pidfile = args.PIDFILE
    if pidfile:
        plugins.PIDFile(engine, pidfile).subscribe()

    if args.USER:
        uid = pwd.getpwnam(args.USER).pw_uid
        gid = grp.getgrnam(args.GROUP).gr_gid
        plugins.DropPrivileges(engine, uid=uid, gid=gid, umask=033).subscribe()

    config_file = args.CONFIG

# Load the configuration file
if not os.path.isfile(config_file):
    config_file = '/etc/pellmon.conf'
if not os.path.isfile(config_file):
    config_file = '/usr/local/etc/pellmon.conf'
if not os.path.isfile(config_file):
    print "config file not found"
    sys.exit(1)
parser.read(config_file)

# The RRD database, updated by pellMon
try:
    polling = True
    db = parser.get('conf', 'database')
    graph_file = os.path.join(os.path.dirname(db), 'graph.png')
except ConfigParser.NoOptionError:
    polling = False
    db = ''

# the colors to use when drawing the graph
colors = parser.items('graphcolors')
colorsDict = {}
for key, value in colors:
    colorsDict[key] = value

# Get the names of the polled data
polldata = parser.items("pollvalues")
# Get the names of the polled data
rrd_ds_names = parser.items("rrd_ds_names")
ds_names = {}
for key, value in rrd_ds_names:
    ds_names[key] = value

credentials = parser.items('authentication')
logfile = parser.get('conf', 'logfile')

timeChoices = ['time1h', 'time3h', 'time8h', 'time24h', 'time3d', 'time1w']
timeNames  = ['1 hour', '3 hours', '8 hours', '24 hours', '3 days', '1 week']
timeSeconds = [3600, 3600*3, 3600*8, 3600*24, 3600*24*3, 3600*24*7]
ft=False
fc=False
for a,b in polldata:
    if b=='feeder_capacity':
        fc=True
    if b=='feeder_time':
        ft=True
if fc and ft:
    consumption_graph=True
    consumption_file = os.path.join(os.path.dirname(db), 'consumption.png')
else:
    consumption_graph=False

global_conf = {
        'global':   { 'server.environment': 'debug',
                      'tools.sessions.on' : True,
                      'tools.sessions.timeout': 7200,
                      'tools.auth.on': True,
                      'server.socket_host': '0.0.0.0',
                      'server.socket_port': int(parser.get('conf', 'port')),
                    }
              }
app_conf =  {'/media':
                {'tools.staticdir.on': True,
                 'tools.staticdir.dir': MEDIA_DIR},
             '/favicon.ico':
                {'tools.staticfile.on':True,
                 'tools.staticfile.filename': FAVICON}
            }

current_dir = os.path.dirname(os.path.abspath(__file__))
cherrypy.config.update(global_conf)

if __name__=="__main__":

    cherrypy.tree.mount(PellMonWeb(), '/', config=app_conf)
    if hasattr(engine, "signal_handler"):
        engine.signal_handler.subscribe()
    if hasattr(engine, "console_control_handler"):
        engine.console_control_handler.subscribe()

    # Always start the engine; this will start all other services
    try:
        engine.start()
    except:
        # Assume the error has been logged already via bus.log.
        sys.exit(1)
    else:
        engine.block()

#    cherrypy.quickstart(PellMonWeb(), config=app_conf)

else:
    # The dbus main_loop thread can't be started before double fork to daemon, the
    # daemonizer plugin has priority 65 so it's executed before dbus_handler.setup
    cherrypy.engine.subscribe('start', dbus.setup, 90)
    dbus = Dbus_handler('SYSTEM')
    cherrypy.tree.mount(PellMonWeb(), '/', config=app_conf)

