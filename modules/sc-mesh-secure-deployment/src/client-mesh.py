#!/usr/bin/python

import argparse
import json
import yaml
import subprocess
import time
import hashlib
import re

import netifaces
from getmac import get_mac_address
import requests
from termcolor import colored
from pathlib import Path


# Get the mesh_com config
print('> Loading yaml conf... ')
try:
    yaml_conf = yaml.safe_load(open('src/mesh_com.conf', 'r'))
    conf = yaml_conf['client']
    debug = yaml_conf['debug']
    print(conf)
except (IOError, yaml.YAMLError) as error:
    print(error)
    exit()


# Construct the argument parser
ap = argparse.ArgumentParser()


# Add the arguments to the parser
ap.add_argument("-s", "--server", required=True, help="Server IP:Port Address. Ex: 'http://192.168.15.14:5000'")
ap.add_argument("-c", "--certificate", required=True)
args = ap.parse_args()


# Connect to server
URL = args.server
print('> Connecting to server: ' + str(URL))


def get_os():
    proc = subprocess.Popen(['lsb_release', '-a'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    for element in out.split():
        aux = element.decode('utf-8')
        if 'Ubuntu' in aux:
            os = aux
    return os

def get_data(cert_file, os):
    message = '/api/add_message/' + os
    response = requests.post(URL + message,
                             files={'key': open(cert_file, 'rb')})
    if response.content == b'Not Valid Certificate':
        print(colored('Not Valid Certificate', 'red'))
        exit()
    else:
        if debug:
            print('> Encrypted message: ' + str(response.content))
        with open('payload.enc', 'wb') as file:
            file.write(response.content)


def decrypt_response():  # assuming that data is on a file called payload.enc generated on the function get_data
    proc = subprocess.Popen(['src/ecies_decrypt', args.certificate], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    aux_list = [element.decode() for element in out.split()]
    # print(aux_list)
    server_cert = aux_list[:39]
    # Get server configuration json using regex
    new_list = ''.join(aux_list)
    pattern = re.compile(r'\{(?:[^{}])*\}')
    new_list = pattern.findall(new_list)
    output_dict = serializing(new_list)
    if debug:
        print('> Decrypted Message: ', output_dict)

    return output_dict, server_cert


def serializing(new_list):
    joined_list = ''.join(new_list)
    output_dict = joined_list.replace("\'", '"')

    return output_dict


def verify_certificate(old, new):
    """
    Here we are validating the hash of the certificate. This is giving us the integrity of the file, not if the
    certificate is valid. To validate if the certificate is valid, we need to verify the features of the certificate
    such as NotBefore, notAfter, crl file and its signature, issuer validity, if chain is there then this for all but
    for this we need to use x509 certificates.

    """
    proc = subprocess.Popen(['src/ecies_decrypt', args.certificate], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    old = [element.decode() for element in out.split()]
    local_cert = old[:39]
    old_aux = serializing(local_cert)
    new_aux = serializing(new)
    old_md5 = hashlib.md5(old_aux.encode('utf-8')).hexdigest()
    new_md5 = hashlib.md5(new_aux.encode('utf-8')).hexdigest()

    return old_md5 == new_md5


def get_interface(pattern):
    interface_list = netifaces.interfaces()
    interface = filter(lambda x: pattern in x, interface_list)
    pre = list(interface)
    if not pre:
        print('> ERROR: Interface ' + pattern + ' not found!')
    else:
    if not list(interface):
        mesh_interface = filter(lambda x: 'wla' in x or 'wlp' in x, interface_list)
        return  list(mesh_interface)[0]
        return pre[0]


def ubuntu_gw(gw_inf):
    print('> Configuring Ubuntu gateway node with gw_inf:' + str(gw_inf) + '...')
    # Create Gateway Service
    subprocess.call('sudo cp ../../common/scripts/mesh-gw.sh /usr/local/bin/.', shell=True)
    subprocess.call('sudo chmod 744 /usr/local/bin/mesh-gw.sh', shell=True)
    subprocess.call('sudo cp services/gw@.service /etc/systemd/system/.', shell=True)
    subprocess.call('sudo chmod 644 /etc/systemd/system/gw@.service', shell=True)
    subprocess.call('sudo systemctl enable gw@' + str(gw_inf) + '.service', shell=True)
    # IF inf is wl, auto connect wlx to AP at boot using wpa_supplicant
    if "wl" in str(gw_inf):
        subprocess.call('sudo cp conf/ap.conf /etc/wpa_supplicant/wpa_supplicant-' + str(gw_inf) + '.conf', shell=True)
        subprocess.call('chmod 600 /etc/wpa_supplicant/wpa_supplicant-' + str(gw_inf) + '.conf', shell=True)
        subprocess.call('sudo systemctl enable wpa_supplicant@' + str(gw_inf) + '.service', shell=True)


def ubuntu_node(gateway):
    print('> Configuring Ubuntu mesh node...')
    # Create default route service
    subprocess.call('route add default gw ' + gateway + ' bat0', shell=True)  # FIXME: Is this line necessary?
    subprocess.call('sudo cp ../../common/scripts/mesh-default-gw.sh /usr/local/bin/.', shell=True)
    subprocess.call('sudo chmod 744 /usr/local/bin/mesh-default-gw.sh', shell=True)
    subprocess.call('sudo cp services/default@.service /etc/systemd/system/.', shell=True)
    subprocess.call('sudo chmod 644 /etc/systemd/system/default@.service', shell=True)
    subprocess.call('sudo systemctl enable default@' + gateway + '.service', shell=True)


def create_config_ubuntu(response):
    res = json.loads(response)
    print('> Interfaces: ' + str(res))
    address = res['addr']
    # Create mesh service config
    Path("/etc/mesh_com").mkdir(parents=True, exist_ok=True)
    with open('/etc/mesh_com/mesh.conf', 'w') as mesh_config:
        mesh_config.write('MODE=mesh\n')
        mesh_config.write('IP=' + address + '\n')
        mesh_config.write('MASK=255.255.255.0\n')
        mesh_config.write('MAC=' + res['ap_mac'] + '\n')
        mesh_config.write('KEY=' + res['key'] + '\n')
        mesh_config.write('ESSID=' + res['ssid'] + '\n')
        mesh_config.write('FREQ=' + str(res['frequency']) + '\n')
        mesh_config.write('TXPOWER=' + str(res['tx_power']) + '\n')
        mesh_config.write('COUNTRY=fi\n')
        mesh_config.write('PHY=phy1\n')
    # Are we a gateway node? If we are we need to set up the routes
    if res['gateway'] and conf['gw_service']:
        print("============================================")
        gw_inf = get_interface(conf['gw_inf'])
        ubuntu_gw(gw_inf)
    elif conf['dflt_service']:
        # We aren't a gateway node, set up the default route (to gw) service
        prefix = address.split('.')[:-1]
        prefix = '.'.join(prefix)
        mesh_gateway = prefix + '.2'
        ubuntu_node(mesh_gateway)
    # Set hostname
    if conf['set_hostname']:
        print('> Setting hostname...')
        nodeId = int(res['addr'].split('.')[-1]) - 1  # the IP is sequential, then it gives the nodeId.
        subprocess.call('sudo hostnamectl set-hostname node' + str(nodeId), shell=True)
        subprocess.call('echo ' + '"' + address + '\t' + 'node' + str(nodeId) + '"' + ' >' + '/etc/hosts', shell=True)
    # Final settings
    if conf['disable_networking']:
        subprocess.call('sudo nmcli networking off', shell=True)
        subprocess.call('sudo systemctl stop network-manager.service', shell=True)
        subprocess.call('sudo systemctl disable network-manager.service', shell=True)
        subprocess.call('sudo systemctl disable wpa_supplicant.service', shell=True)
    # Copy mesh service to /etc/systemd/system/
    if conf['mesh_service']:
        mesh_interface = get_interface(conf['mesh_inf'])
        subprocess.call('sudo cp ../../common/scripts/mesh-' + res['type'] + '.sh /usr/local/bin/.', shell=True)
        subprocess.call('sudo chmod 744 /usr/local/bin/mesh-' + res['type'] + '.sh', shell=True)
        subprocess.call('sudo cp services/mesh@.service /etc/systemd/system/.', shell=True)
        subprocess.call('sudo chmod 664 /etc/systemd/system/mesh@.service', shell=True)
        subprocess.call('sudo systemctl enable mesh@' + mesh_interface + '.service', shell=True)
        # Ensure our nameserver persists as 8.8.8.8
        # subprocess.call('sudo cp conf/resolved.conf /etc/systemd/resolved.conf', shell=True) # FIXME: I don't actually think we need this any more...
        time.sleep(2)
        subprocess.call('reboot', shell=True)


if __name__ == "__main__":
    os = get_os()
    local_cert = args.certificate
    get_data(local_cert, os)
    res, server_cert = decrypt_response()
    if verify_certificate(local_cert, server_cert):
        print(colored('> Valid Server Certificate', 'green'))
        mac = get_mac_address(interface=get_interface(conf['mesh_inf']))
        response = requests.post(URL + '/mac/' + mac)
        if os == 'Ubuntu':
            create_config_ubuntu(res)
    else:
        print(colored("Not Valid Server Certificate", 'red'))
        exit(0)