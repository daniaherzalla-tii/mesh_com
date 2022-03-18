from PyKCS11 import *
import subprocess
import hashlib
import argparse

BUF_SIZE = 65536  # lets read stuff in 64kb chunks!
LIB = "/usr/lib/softhsm/libsofthsm2.so"
os.environ['PYKCS11LIB'] = LIB

debug = True

'''
TODO:create a function to verify if keys exist and are valid
'''

ap = argparse.ArgumentParser()
ap.add_argument("-cl", "--clean", required=False, default=False, help='Delete all keys', action='store_false')
args = ap.parse_args()


def clean_all():
    pkcs11 = PyKCS11Lib()
    pkcs11.load()  # define environment variable PYKCS11LIB=YourPKCS11Lib

    # get 1st slot
    slot = pkcs11.getSlotList(tokenPresent=True)[0]

    session = pkcs11.openSession(slot, CKF_SERIAL_SESSION | CKF_RW_SESSION)
    session.login("1234")

    keys = session.findObjects()
    for key in range(len(keys)):
        session.destroyObject(keys[key])


def encrypt_response(message,
                     name):  # assuming that data is on a file called payload.enc generated on the function get_data

    pkcs11 = PyKCS11Lib()
    pkcs11.load()  # define environment variable PYKCS11LIB=YourPKCS11Lib

    # get 1st slot
    slot = pkcs11.getSlotList(tokenPresent=True)[0]

    session = pkcs11.openSession(slot, CKF_SERIAL_SESSION | CKF_RW_SESSION)
    session.login("1234")

    keys = session.findObjects()
    for key in range(len(keys)):
        aux = keys[key].to_dict()
        if aux['CKA_LABEL'] == name:
            pubKey = keys[key]

    encr = session.encrypt(pubKey, message)
    if debug:
        print(f'> Encrypted message: {bytes(encr)}')
    # logout
    session.logout()
    session.closeSession()
    return bytes(encr)


def decrypt_response(encr):  # assuming that data is on a file called payload.enc generated on the function get_data
    pkcs11 = PyKCS11Lib()
    pkcs11.load()  # define environment variable PYKCS11LIB=YourPKCS11Lib

    # get 1st slot
    slot = pkcs11.getSlotList(tokenPresent=True)[0]

    session = pkcs11.openSession(slot, CKF_SERIAL_SESSION | CKF_RW_SESSION)
    session.login("1234")
    privKey = session.findObjects([(CKA_CLASS, CKO_PRIVATE_KEY)])[0]
    dec = session.decrypt(privKey, encr)
    if type(dec) == 'PyKCS11.ckbytelist':
        dec = bytes(dec)
    if debug:
        print(f'> Decrypted message: {str(dec)}')
    # logout
    session.logout()
    session.closeSession()
    return dec


def delete_key(node_name):
    label = f'--label={node_name}'
    command = ['pkcs11-tool', '--module', LIB, '--delete-object', label, '--type=pubkey']
    subprocess.call(command, shell=False)


def import_cert(client_key, node_name):
    LIB = '/usr/lib/softhsm/libsofthsm2.so'
    filename = f'{node_name}.der'
    id = node_name.split('_')[-1]
    with open(filename, 'wb') as writer:
        writer.write(client_key.read())
    command = ['pkcs11-tool', '--module', LIB, '-l', '--pin', '1234', '--write-object', filename, '--type', 'pubkey',
               '--id', id, '--label', node_name]
    subprocess.call(command, shell=False)


def verify_hsm(msg, sig, name):
    pkcs11 = PyKCS11Lib()
    pkcs11.load()  # define environment variable PYKCS11LIB=YourPKCS11Lib
    # get 1st slot
    slot = pkcs11.getSlotList(tokenPresent=True)[0]
    session = pkcs11.openSession(slot, CKF_SERIAL_SESSION | CKF_RW_SESSION)
    session.login("1234")
    keys = session.findObjects()
    for key in range(len(keys)):
        aux = keys[key].to_dict()
        if aux['CKA_LABEL'] == name:
            pubKey = keys[key]  ##check here need to verify if not exported
    ver = session.verify(pubKey, msg, sig)
    # logout
    session.logout()
    session.closeSession()
    return ver


def sign_hsm(msg):
    pkcs11 = PyKCS11Lib()
    pkcs11.load()  # define environment variable PYKCS11LIB=YourPKCS11Lib
    # get 1st slot
    slot = pkcs11.getSlotList(tokenPresent=True)[0]
    session = pkcs11.openSession(slot, CKF_SERIAL_SESSION | CKF_RW_SESSION)
    session.login("1234")
    privKey = session.findObjects([(CKA_CLASS, CKO_PRIVATE_KEY)])[0]
    sig = session.sign(privKey, msg)
    # logout
    session.logout()
    session.closeSession()
    return sig


def verify_certificate(sig_received, node_name, dig_received, cert):
    blk = hashlib.blake2s()
    with open(cert, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            blk.update(data)
    dig = blk.hexdigest()
    if dig == dig_received.decode('UTF-8'):
        return verify_hsm(dig_received, sig_received, node_name)


def hashSig(cert):
    blk = hashlib.blake2s()
    with open(cert, 'rb') as stream:
        while True:
            data = stream.read(BUF_SIZE)
            if not data:
                break
            blk.update(data)
        dig = blk.hexdigest()
        sig = sign_hsm(dig)
        return dig, sig


if __name__ == "__main__":
    if args.clean:
        clean_all()
