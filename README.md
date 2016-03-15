This project uses the [Ademco TPI provided by Eyez-On](http://forum.eyez-on.com/FORUM/viewtopic.php?f=6&t=301).  It processes events and passes them to the SmartThings API.

This project started as a fork of [HoneyAlarmServer](https://github.com/MattTW/HoneyAlarmServer), which in turn was based on [AlarmServer for DSC panels](https://github.com/juggie/AlarmServer) - credit to them for the base code.   However, it ended up evolving past the point where it made sense maintain a single codebase.

This is still beta software.  SmartAlarmServer was tested with Envisalink 4 and Honeywell Vista 20p panel; HoneyAlarmServer was tested with an Envisalink 3 and Honeywell Vista 15p panel.

#### What Works ####

 + Keypad, zone, and partition updates sent by the Envisalink as documented in the TPI are tracked by the Alarm Server and forwarded to SmartThings.
 + SmartThings SmartApp integration lets user select which zones to track and creates SmartThings devices to represent alarm system state: contact sensors, motion sensors, and smoke sensors.  These devices can be integrated individually or as a group with other SmartThings systems and SmartThings Smart Home Monitor.
 + Because EnvisaLink zone status updates are buggy and inconsistent, we derive zone status from keypad updates which are sent by the Vista control panel and are much more reliable.
 + Bug fixes to parsing of zone polling updates.
 + Asynchronous posting of SmartThings updates so the main thread can continue listening to EnvisaLink.
 + Full sensor state is transmitted with every update so SmartThings will not get out of sync if updates are dropped.

#### What Doesn't Work ####

+ The Web UI from AlarmServer and HoneyAlarmServer has been removed entirely.
+ No way to arm/disarm the Vista panel remotely or trigger the siren.  The idea is to use SmartThings Smart Home Monitor as the security system instead of the Vista panel alarm.

Config
------
Please see alarmserver-example.cfg and rename to alarmserver.cfg and
customize to requirements.
