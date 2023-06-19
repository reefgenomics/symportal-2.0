#!/usr/bin/env python3
import os
import sys
import time
import glob
import logging
import paramiko

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')


class SFTPClient:
    def __init__(self, hostname, username, password):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.client = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.hostname, username=self.username, password=self.password)

    def disconnect(self):
        if self.client is not None:
            self.client.close()

    def copy_submission(self, local_path, remote_path):
        if self.client is None:
            raise Exception("Not connected to SFTP server.")

        if not os.path.isdir(local_path):
            raise Exception("Invalid local directory path.")

        sftp = self.client.open_sftp()

        # Extract the username and submission name from the local_path
        username = os.path.basename(os.path.dirname(local_path))
        submission_name = os.path.basename(local_path)

        # We assume the user folder can exist
        try:
            sftp.chdir(f'{remote_path}/{username}')
        except IOError:
            sftp.mkdir(f'{remote_path}/{username}')

        remote_submission_path = f'{remote_path}/{username}/{submission_name}'
        try:
            sftp.mkdir(remote_submission_path)
            sftp.put(local_path, remote_submission_path, preserve_mtime=True)
        finally:
            sftp.close()


def generate_lock_file(filepath):
    with open(filepath, 'w') as file:
        return


def remove_lock_file(filepath):
    if os.path.isfile(filepath):
        os.remove(filepath)
        logging.info(
            f'File the lock file {filepath} has been successfully removed.')
    else:
        logging.info(f'File {filepath} does not exist.')


def lock_file_exists(filepath):
    if os.path.exists(filepath):
        return True
    else:
        return False


def get_submissions_to_transfer(base_dir):
    # If folder exists and it is not empty
    if os.path.isdir(base_dir) and os.listdir(base_dir):
        return [directory for directory in
                glob.glob(os.path.join(base_dir, '*', '*')) if
                os.path.isdir(directory)]
    else:
        return list()


def select_submission(submissions):
    if len(submissions) == 0:
        sys.exit()
    return submissions[0]


if __name__ == '__main__':

    lock_file = f'/var/lock/{os.path.basename(__file__)}'

    # Only one cron job process can be running
    if lock_file_exists(lock_file):
        logging.info("Cron job process exists for the current script. Exiting.")
        sys.exit(0)

    # Generate the lock file to have only one cron running process
    generate_lock_file(lock_file)
    logging.info(f'Lock file generated. Current process ID: {os.getpid()}')

    submissions = get_submissions_to_transfer(base_dir='/app/sp_app/uploads')
    logging.info(f'Available submissions to transfer: {submissions}')

    logging.info(f'Establish connection with SFTP Server: {os.getenv("SYMPORTAL_SFTP_SERVER_CONTAINER")}.')
    sftp_client = SFTPClient(
        os.getenv('SYMPORTAL_SFTP_SERVER_CONTAINER'),
        os.getenv('SFTP_USERNAME'),
        os.getenv('SFTP_PASSWORD')
    )
    try:
        # Connect to the SFTP server
        print('TRYYYYYYYYYYYYYYYYYYYYYY')
        sftp_client.connect()
        sftp = sftp_client.client.open_sftp()
        sftp.getcwd()
        sftp_client.copy_submission(select_submission(submissions), os.getenv("SFTP_HOME"))
    finally:
        sftp_client.disconnect()
        remove_lock_file(lock_file)
