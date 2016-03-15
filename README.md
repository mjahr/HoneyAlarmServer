This project uses the [Ademco TPI provided by Eyez-On](http://forum.eyez-on.com/FORUM/viewtopic.php?f=6&t=301).  It processes events and passes them to the SmartThings API.

This project started as a fork of [HoneyAlarmServer](https://github.com/MattTW/HoneyAlarmServer), which in turn was based on [AlarmServer for DSC panels](https://github.com/juggie/AlarmServer) - credit to them for the base code.   However, it ended up evolving past the point where it made sense maintain a single codebase.

This is still beta software.  SmartAlarmServer was tested with Envisalink 4 and Honeywell Vista 20p panel; HoneyAlarmServer was tested with an Envisalink 3 and Honeywell Vista 15p panel.

#### What Works ####

 + Keypad, zone, and partition updates sent by the Envisalink as documented in the TPI are tracked by the Alarm Server and forwarded to SmartThings.
 + SmartThings SmartApp integration lets user select which zones to track and creates SmartThings devices to represent alarm system state: contact sensors, motion sensors, and smoke sensors.
 + Better zone status tracking by parsing keypad updates.  This works around inconsistent zone state change messages from Envisalink.
 +

#### What Doesn't Work ####

+ The Web UI from AlarmServer and HoneyAlarmServer has been removed entirely.
+ No way to arm/disarm the system remotely or trigger the siren.  The idea is to use SmartThings Smart Home Monitor as the security system instead of the Vista panel alarm.
+ Zone state change messages from the TPI seem to be buggy and work sporadically, if you aren't seeing them when you should try rebooting your envisalink.
+ The Alarm state returned by the HTTP api call only returns partition state information so far (it does not return all the state expected by the Web UI)
+ Make HTTP API commands synchronous so they can return success/failure or results instead of just acknowledging the command


Plugin System
-------------
A basic plugin system is available.   The plugins directory is searched for any python files containing classes that inherit from BasePlugin.

These classes override whatever events they are interested in responding to.  A cfg file of the format *ClassName*.cfg is automatically loaded if present.

See the plugin-examples directory for a few samples:

*indigoPlugin* - Communicates status with Indigo home automation servers

*pushoverPlugin* - Sends notifications via the Pushover API to iOS/Android/Desktops

*sssPlugin* - Communicates with Synology Survelliance Station

Config
-------
Please see the alarmserver-example.cfg and rename to alarmserver.cfg and
customize to requirements.

There are example plugins in the plugin-examples directory.  Copy/modify and place them in the plugins directory along with a valid cfg file to use them



OpenSSL Certificate Howto
-------------------

The ssl certificates that are provided are intended for demo purposes only.
Please use openssl to generate your own. A quick HOWTO is below.

To generate a self signed cert issue the following in a command prompt:
`openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout server.key -out server.crt`

Openssl will ask you some questions. The only semi-important one is the 'common name' field.
You want this set to your servers fqdn. IE alarmserver.example.com.

If you have a real ssl cert from a certificate authority and it has intermediate certs then you'll need to bundle them all up or the webbrowser will complain about it not being a valid cert. To bundle the certs use cat to include your cert, then the intermediates (ie cat mycert.crt > combined.crt; cat intermediates.crt >> combined.crt)


Dependencies:
-------------

On windows, pyOpenSSL is required.
http://pypi.python.org/pypi/pyOpenSSL


Launchers
---------
* [MacOSX](https://github.com/gschrader/Alarm-Server-Launcher)

REST API Info
-------------

*/api*

* Returns a JSON dump of all currently known states

*/api/partition?changeTo=1*

* change to the given partition. Envisalink remembers this as the partition for future commands
  * Required param = **changeTo** - a partition number between 1 and 8

*/api/alarm/arm*

* arm the security system

*/api/alarm/stayarm*

* Stay arm (a.k.a. Arm Home)

*/api/alarm/disarm*

* Disarm system

arm,stayarm,disarm can all take optional param **alarmcode**.  If alarmcode param is missing the config file value is used instead
