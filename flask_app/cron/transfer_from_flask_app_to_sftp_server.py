#!/usr/bin/env python3
import os
import sys
import glob
import shutil
import hashlib
import logging
import paramiko

from sp_app import app, db
from sp_app.models import Submission

from symportal_kitchen.utils.utils import (
    generate_lock_file, remove_lock_file, lock_file_exists)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class SFTPClient:
    def __init__(self, hostname, username, password, local_path, remote_path):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.client = None
        self.local_path = local_path
        self.remote_path = remote_path
        # Extract the username and submission name from the local_path
        self.remote_path_username = os.path.basename(
            os.path.dirname(self.local_path))
        self.submission_name = os.path.basename(self.local_path)
        self.remote_submission_path = \
            f'{self.remote_path}/{self.remote_path_username}/{self.submission_name}'

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.hostname, username=self.username,
                            password=self.password)

    def disconnect(self):
        if self.client is not None:
            self.client.close()

    def create_remote_dirs(self):
        folders = self.remote_submission_path.split('/')
        current_path = ''

        sftp = self.client.open_sftp()

        try:
            for folder in folders:
                if folder:
                    current_path += '/' + folder
                    try:
                        sftp.chdir(current_path)
                    except IOError:
                        try:
                            sftp.mkdir(current_path)
                        except IOError as e:
                            # If the folder creation failed, raise an exception or handle the error
                            logging.error(
                                f'Failed to create folder: {current_path}. Error: {str(e)}')
            logging.info(f'Remote submission path exists or were created: {self.remote_submission_path}')
        finally:
            sftp.close()

    def copy_submission(self):
        if self.client is None:
            raise Exception("Not connected to SFTP server.")

        if not os.path.isdir(self.local_path):
            raise Exception(
                f'Invalid local directory path : {self.local_path}.')

        sftp = self.client.open_sftp()

        try:
            for item in os.listdir(self.local_path):
                # Copy file to remote
                sftp.put(os.path.join(self.local_path, item),
                         os.path.join(self.remote_submission_path, item))
                logging.info(f'Done with {item}.')
        except Exception as e:
            logging.error(f'An error has occurred: {str(e)}')
        finally:
            sftp.close()

    def _create_md5sum_dictionary(self):
        md5sum_dict = {}

        try:
            file_paths = glob.glob(os.path.join(self.local_path, '*.md5sum'))
            if len(file_paths) == 0:
                raise FileNotFoundError(
                    f'No md5sum files found in the specified folder: {self.local_path}.')

            # Assuming there is only one md5sum file in the folder
            file_path = file_paths[0]

            with open(file_path, 'r') as file:
                md5sum_dict = {os.path.basename(line.strip().split('  ')[1]):
                                   line.strip().split('  ')[0] for line in file}
        except FileNotFoundError as e:
            logging.error(e)
        except Exception as e:
            print(f'An error occurred while processing the file: {e}.')

        return md5sum_dict

    def md5sum_check(self):

        md5sum_dict = self._create_md5sum_dictionary()

        sftp = self.client.open_sftp()

        for filename, existing_checksum in md5sum_dict.items():
            remote_file_path = os.path.join(self.remote_submission_path,
                                            filename)
            # Calculate the MD5 checksum of the remote file
            md5_hash = hashlib.md5()
            with sftp.open(remote_file_path, 'rb') as remote_file:
                for chunk in iter(lambda: remote_file.read(4096), b''):
                    md5_hash.update(chunk)

            remote_checksum = md5_hash.hexdigest()
            # Compare the remote checksum with the existing checksum
            if remote_checksum == existing_checksum:
                logging.info(
                    f'The MD5 checksum of {filename} matches the existing checksum.')
            else:
                error_message = \
                    f'The MD5 checksum of {filename} does not match the existing checksum.'
                logging.error(error_message)
                raise Exception(error_message)
        logging.info('The MD5 checksum completed.')
        return True

    def update_submission_status(self):
        with app.app_context():
            s = Submission.query.filter(
                Submission.name == self.submission_name).one()
            s.progress_status = 'transfer_to_sftp_server_complete'
            db.session.commit()
            logging.info(
                f'The submission status has been updated to {s.progress_status}.')

    def delete_local_submission(self):
        try:
            shutil.rmtree(self.local_path)
            logging.info(
                f'Directory {self.local_path} and its contents were successfully removed.')
        except FileNotFoundError:
            logging.warning(f'Directory {self.local_path} does not exist.')
        except Exception as e:
            logging.error(
                f'An error occurred while removing directory {self.local_path}: {e}')


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
        logging.warning('There are no available submissions.')
        sys.exit(1)
    return submissions[0]


if __name__ == '__main__':

    lock_file = f'/var/lock/{os.path.basename(__file__)}.lock'

    # Only one cron job process can be running
    if lock_file_exists(lock_file):
        sys.exit(1)

    # Main try block that always finishes with deleting of lock file
    try:
        # Generate the lock file to have only one cron running process
        generate_lock_file(lock_file)

        submissions = get_submissions_to_transfer(
            base_dir='/app/sp_app/uploads')
        logging.info(f'Available submissions to transfer: {submissions}')

        logging.info(
            f'Establish connection with SFTP Server: {os.getenv("SYMPORTAL_SFTP_SERVER_CONTAINER")}.')
        sftp_client = SFTPClient(
            hostname=os.getenv('SYMPORTAL_SFTP_SERVER_CONTAINER'),
            username=os.getenv('SFTP_USERNAME'),
            password=os.getenv('SFTP_PASSWORD'),
            local_path=select_submission(submissions),
            remote_path=os.path.join(os.getenv('SFTP_HOME'), 'uploads'))

        try:
            # Connect to the SFTP server
            sftp_client.connect()
            sftp_client.create_remote_dirs()
            # Process submission
            sftp_client.copy_submission()
            if sftp_client.md5sum_check():
                sftp_client.update_submission_status()
                sftp_client.delete_local_submission()
        finally:
            sftp_client.disconnect()

    finally:
        remove_lock_file(lock_file)
