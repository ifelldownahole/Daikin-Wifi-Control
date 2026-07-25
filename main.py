import machine
import time
import daikin_ac_utils
import config
from mqttsimple import MQTTClient


"""
Can you hear that? It's the big leagues calling!
Presenting the MICL CLIME, or for long,

Part of the Mobile Integration and Communication Link (MICL) series,
this is the Climate Link and Intelligent Modulation Engine (CLIME).

Yeah, ok I'm sorry I just HAD to make it an acronym that came together as well.
"""



def connect_wifi():
    """Connects to the local wifi network."""
    # Import lib here since I only need it for the connection part. 
    import network
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    if not wifi.isconnected():
        print("Connecting to network....")
        wifi.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        while not wifi.isconnected():
            machine.idle()
    print('Connected! Network config:', wifi.ipconfig("addr4"))

# Call connect_wifi()
connect_wifi()


client = MQTTClient(
    client_id=config.CLIENT_ID, 
    server=config.MQTT_BROKER, 
    user=config.MQTT_USER, 
    password=config.MQTT_PASSWORD
)


print("Connecting to MQTT...")
client.connect()
print("MQTT connected!")



"""
Main loop for the publishing and subscribing to the topics.
The wifi connection stuff should probably be in it's own seperate boot.py file to be honest. 
"""

last_fast_pub = 0

# Slow pub allows longer time to update fan and compressor rpm.
last_slow_pub = 0 

while True:
    
    pass
    
    
