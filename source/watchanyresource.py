import os
import json
import logging
import time
import urllib3
import requests
import websocket, ssl
import subprocess
import threading
import paho.mqtt.client as mqtt
from kubernetes import config
from kubernetes.client import configuration
from subprocess import Popen

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Variables for Kubernetes resource to watch
groupversion = os.environ.get('GROUPANDVERSION')
resourcetype = os.environ.get('RESOURCETYPE')
namespace = os.environ.get('NAMESPACE',"")

# Variables for sending Messages to a broker
mqtt_broker = os.environ.get('MQTTBROKER',"")
mqtt_port = os.environ.get('MQTTPORT',"1883")
mqtt_topic = os.environ.get('MQTTTOPIC',"")

def get_kubeapi_request(httpsession,path,header):
    try:
        response = httpsession.get(path, headers=header, verify=False)
        response.raise_for_status() # Raises an HTTPError for bad responses (4XX or 5XX)
        response.encoding = 'utf-8'
        return response.json()
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error getting resource: {e.response.status_code} for path {path}. Response: {e.response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for path {path}: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON response from {path}: {e}")
    return None # Return None on error

def get_kubeapi_request_streaming(path,header):
    try:
        ws = websocket.create_connection(path, header=header, sslopt={"cert_reqs": ssl.CERT_NONE})
        return ws
    except websocket.WebSocketException as e:
        logging.error(f"WebSocket connection failed for path {path}: {e}")
    except Exception as e: # Catch any other unexpected errors
        logging.error(f"Unexpected error during WebSocket connection to {path}: {e}", exc_info=True)
    return None # Return None on error

def handleMsgThread(msg, mqtt_configured, mqtt_client, mqtt_topic):
    try:
        json_msg = json.loads(msg)
        os.environ["CHANGED_VARIABLE"] = json.dumps(json_msg['object'])
        event_type = json_msg.get('type')
        resource_name = json_msg.get('object', {}).get('metadata', {}).get('name', 'unknown')

        if event_type == "ADDED":
            logging.info(f"Event: ADDED for resource type {resourcetype} (name: {resource_name}). Executing scripts in /app/added...")
            script_dir = '/app/added'
        elif event_type == "MODIFIED":
            logging.info(f"Event: MODIFIED for resource type {resourcetype} (name: {resource_name}). Executing scripts in /app/modified...")
            script_dir = '/app/modified'
        elif event_type == "DELETED":
            logging.info(f"Event: DELETED for resource type {resourcetype} (name: {resource_name}). Executing scripts in /app/deleted...")
            script_dir = '/app/deleted'
        else:
            logging.debug(f"Event type {event_type if event_type else 'UNKNOWN'} received for resource {resource_name}, no action defined.")
            return # No further processing if event type is not handled

        if not os.path.exists(script_dir):
            logging.warning(f"Script directory {script_dir} not found. Skipping script execution.")
            return

        for file_name in sorted(os.listdir(script_dir)):
            script_path = os.path.join(script_dir, file_name)
            if not os.access(script_path, os.X_OK):
                logging.warning(f"Script {script_path} is not executable. Skipping.")
                continue
            
            logging.info(f"Executing script: {script_path}")
            try:
                p = Popen([script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, stdin=subprocess.DEVNULL)
                stdout, stderr = p.communicate() 
                if stdout:
                    logging.info(f"Script {script_path} STDOUT:\n{stdout.decode().strip()}")
                if stderr:
                    logging.warning(f"Script {script_path} STDERR:\n{stderr.decode().strip()}")
                if p.returncode != 0:
                    logging.error(f"Script {script_path} exited with error code {p.returncode}")
            except FileNotFoundError:
                logging.error(f"Script {script_path} not found.")
            except PermissionError:
                logging.error(f"Permission denied for script {script_path}.")
            except Exception as e:
                logging.error(f"Error executing script {script_path}: {e}", exc_info=True)
        
        # MQTT Publishing (moved inside the main try block of the thread)
        if mqtt_configured:
            if mqtt_client and mqtt_client.is_connected():
                # Publishing the raw message `msg` as received from Kubernetes
                m_info = mqtt_client.publish(mqtt_topic, msg, qos=1)
                try:
                    m_info.wait_for_publish(timeout=1.0)
                    if m_info.rc != mqtt.MQTT_ERR_SUCCESS:
                        logging.warning(f"MQTT publish failed with code {m_info.rc} for topic {mqtt_topic} (resource: {resource_name}, event: {event_type})")
                except RuntimeError:
                    logging.warning(f"MQTT publish call did not complete in time for topic {mqtt_topic} (resource: {resource_name}, event: {event_type})")
                except ValueError: 
                    logging.warning(f"MQTT publish timeout value invalid for topic {mqtt_topic} (resource: {resource_name}, event: {event_type})")
            else:
                logging.warning(f"MQTT client not connected. Cannot publish message for resource {resource_name}, event {event_type} to topic {mqtt_topic}.")

    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON from message: {msg}. Error: {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Unexpected error in handleMsgThread: {e}", exc_info=True)

    # metadata = json_msg['object']['metadata'] # This part seems unused, can be removed or logged if needed
    # if metadata:
    #     resource_version = json_msg['object']['metadata']['resourceVersion']

def main():
    k8s_host = ""
    k8s_token = ""
    k8s_headers = ""
    mqtt_configured = False

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if not groupversion or not resourcetype:
        logging.error("Essential environment variables GROUPANDVERSION or RESSOURCETYPE are not set. Exiting.")
        exit(1)
    logging.info(f"Configuration - GroupVersion: {groupversion}, ResourceType: {resourcetype}, Namespace: {namespace if namespace else 'ALL'}")
 
    if not os.environ.get('INCLUSTER_CONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    k8s_host:str = configuration.Configuration()._default.host
    k8s_token = configuration.Configuration()._default.api_key['authorization']
    k8s_headers = {"Accept": "application/json, */*", "Authorization": k8s_token}
    k8s_session = requests.session() # This session is good for general K8s API calls, but not directly used by websocket client

    if not k8s_host or not k8s_token:
        logging.error("Kubernetes host or token is missing from configuration. Exiting.")
        exit(1)

    if groupversion == "v1":
        api_path = 'api/'+groupversion
    else:
        api_path = 'apis/'+groupversion

    if namespace:
        api_obj = 'namespaces/'+namespace+'/'+resourcetype
    else:
        api_obj = resourcetype

    uri = api_path+'/'+api_obj
    logging.info(f"Connecting to {k8s_host}/{uri}")

    if (mqtt_broker != "" and mqtt_topic == ""):
        logging.info("MQTT Broker specified but Topic is not. MQTT Disabled.")
    elif (mqtt_broker == "" and mqtt_topic != ""):
        logging.info("MQTT Topic specified but Broker is not. MQTT Disabled.")
    elif (mqtt_broker == "" and mqtt_topic == ""):
        logging.info("MQTT Broker and Topic not specified. MQTT Disabled.")
    else:
        logging.info(f"MQTT Configured. Broker: {mqtt_broker}, Port: {mqtt_port}, Topic: {mqtt_topic}")
        mqtt_configured = True

    if mqtt_configured == True:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        try:
            mqtt_client.connect(mqtt_broker, int(mqtt_port), 60)
        except Exception as e:
            logging.error(f"Failed to connect to MQTT broker: {e}")
            mqtt_configured = False # Disable MQTT if connection fails
        if mqtt_configured: # Proceed only if connection was successful
            mqtt_client.loop_start()      
    
    while True:
        init_res_version_data = get_kubeapi_request(k8s_session,k8s_host + '/' + uri, k8s_headers) # k8s_session is fine here
        if init_res_version_data and 'metadata' in init_res_version_data and 'resourceVersion' in init_res_version_data['metadata']:
            resource_version=init_res_version_data['metadata']['resourceVersion']
            logging.debug(f"Initial resource version: {resource_version}")
        else:
            logging.error("Unable to get the initial resource version or data is malformed. Retrying in 10s...")
            time.sleep(10) # Wait before retrying the whole loop
            continue # Retry fetching initial resource version
        
        cmd_opt='resourceVersion='+resource_version+'&allowWatchBookmarks=false&watch=true'
        ws_url = k8s_host.replace("https://","wss://") + '/' + uri + '?' + cmd_opt
        
        try:
            ws_stream = get_kubeapi_request_streaming(ws_url, k8s_headers) # k8s_headers for websocket
            if not ws_stream: # If connection failed and returned None
                logging.error(f"Failed to connect to WebSocket stream at {ws_url}. Retrying in 5s.")
                time.sleep(5)
                continue # Retry the outer while loop

            logging.info(f"Successfully connected to WebSocket stream at {ws_url}")
            while True:
                try:
                    msg = ws_stream.recv()
                    if not msg: # msg is empty or None, connection might be closed by server
                        logging.info("Received empty message from WebSocket, server might have closed connection. Reconnecting...")
                        break 
                    
                    # Pass the raw message to handleMsgThread
                    x = threading.Thread(target=handleMsgThread, args=(msg, mqtt_configured, mqtt_client if mqtt_configured else None, mqtt_topic))
                    x.start()

                except websocket.WebSocketConnectionClosedException as e:
                    logging.warning(f"WebSocket connection closed by server: {e}. Will attempt to reconnect.")
                    break # Break inner loop to reconnect
                except Exception as e: # Catch other errors during message receiving/processing
                    logging.error(f"Error receiving or processing message from WebSocket: {e}", exc_info=True)
                    # Depending on severity, might break or continue. Breaking to reconnect is safer.
                    break 
        except Exception as ex: # Catch errors during ws_stream object creation or initial connection not caught by get_kubeapi_request_streaming
            logging.error(f"Unhandled exception with WebSocket connection to {ws_url}: {ex}. Retrying in 5s.", exc_info=True)
        
        logging.info("Closing WebSocket stream before potential reconnection.")
        if 'ws_stream' in locals() and ws_stream:
            try:
                ws_stream.close()
            except Exception as e_close:
                logging.warning(f"Error closing WebSocket stream: {e_close}")
        time.sleep(5) # Wait 5 seconds before attempting to reconnect the WebSocket

if __name__ == "__main__":
    main()