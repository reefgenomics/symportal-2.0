#!/usr/bin/env python3
import os
import sys
import shutil
import hashlib
import logging
import paramiko
from datetime import datetime

from sp_app import db
from sp_app.models import Submission, SPUser
from transfer_from_flask_app_to_sftp_server import generate_lock_file, lock_file_exists, remove_lock_file

from symportal_kitchen.db_queries.db_queries import get_user_by_id
from symportal_kitchen.email_notifications.submission_status import send_email

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

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.hostname, username=self.username,
                            password=self.password)

    def disconnect(self):
        if self.client is not None:
            self.client.close()

    def copy_analysis_output(self):
        if self.client is None:
            raise Exception('Not connected to SFTP server.')

        if not os.path.isdir(self.local_path):
            os.makedirs(self.local_path, exist_ok=True)
            logging.info(f'Explorer data folder has been created: {self.local_path}.')

        sftp = self.client.open_sftp()

        try:
            for extension in ['.zip', '.md5sum']:
                sftp.get(
                    os.path.join(self.remote_path,
                                 submission.name) + extension,
                    os.path.join(self.local_path, submission.name) + extension
                )
                logging.info(f'Output {submission.name}{extension} file was '
                             f'successfully transferred to Flask App: '
                             f'{self.local_path}.')
        except Exception as e:
            logging.error(f'Exception on channel: {str(e)}.')
        finally:
            sftp.close()

    def md5sum_check(self):

        with open(os.path.join(self.local_path, submission.name) + '.md5sum', 'r') as file:
            md5sum = file.read()
            logging.info(
                f'Expected MD5 checksum of the {os.path.join(self.local_path, submission.name) + ".zip"} archive '
                f'is {md5sum}.')

        md5_hash = hashlib.md5()
        with open(os.path.join(self.local_path, submission.name) + '.zip', 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b''):
                md5_hash.update(chunk)
        actual_md5sum = md5_hash.hexdigest()
        logging.info(f'Actual MD5 checksum of the {os.path.join(self.local_path, submission.name) + ".zip"} archive '
                     f'is {actual_md5sum}.')
        if actual_md5sum == md5sum:
            logging.info('MD5 checksum matches!')
        else:
            logging.error(
                f'MD5 checksum does not match.\n'
                f'    Expected MD5 checksum: {md5sum}.\n'
                f'    Actual MD5 checksum: {actual_md5sum}.')

    def unzip_archive(self, archive_path, destination_dir):
        shutil.unpack_archive(archive_path, destination_dir)
        shutil.move(
            os.path.join(destination_dir, 'html', 'study_data.js'),
            os.path.join(destination_dir, 'study_data.js'))
        logging.info(f'Extracting files from the archive to {destination_dir}.')

    def update_submission_status(self, submission_name):
        s = Submission.query.filter(
            Submission.name == submission_name).one()
        s.study.display_online = True
        s.study.data_explorer = True
        s.progress_status = 'transfer_to_web_server_complete'
        s.transfer_to_web_server_date_time = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        db.session.commit()
        logging.info(
            f'The submission status has been updated to {s.progress_status}.')


def get_submissions_to_transfer(status):
    # Return QuerySet
    return Submission.query. \
        filter(Submission.progress_status == status). \
        filter(Submission.error_has_occured == False). \
        all()


def select_submission(submissions):
    if len(submissions) == 0:
        logging.warning('There are no available submissions.')
        sys.exit(1)
    return submissions[0]


if __name__ == '__main__':

    lock_file = f'/var/lock/{os.path.basename(__file__)}.lock'

    # Only one cron job process can be running
    if lock_file_exists(lock_file):
        logging.info("Cron job process exists for the current script. Exiting.")
        sys.exit(1)

    # Main try block that always finishes with deleting of lock file
    try:
        # Generate the lock file to have only one cron running process
        generate_lock_file(lock_file)

        submission = select_submission(
            get_submissions_to_transfer(
                status='transfer_from_framework_to_sftp_server_complete'))

        logging.info(
            f'Establish connection with SFTP Server: {os.getenv("SYMPORTAL_DATABASE_CONTAINER")}.')
        sftp_client = SFTPClient(
            hostname=os.getenv('SYMPORTAL_SFTP_SERVER_CONTAINER'),
            username=os.getenv('SFTP_USERNAME'),
            password=os.getenv('SFTP_PASSWORD'),
            local_path=os.path.join('/app/sp_app/explorer_data', submission.name),
            remote_path=os.path.join(
                os.getenv('SFTP_HOME'),
                'outputs',
                submission.framework_results_dir_path.split('/')[-2],
                submission.framework_results_dir_path.split('/')[-1])
        )

        try:
            # Connect to the SFTP server
            sftp_client.connect()
            # Process submission
            sftp_client.copy_analysis_output()
            sftp_client.md5sum_check()
            sftp_client.unzip_archive(f'{sftp_client.local_path}/{submission.name}.zip', sftp_client.local_path)
            sftp_client.update_submission_status(submission.name)
            # notify user by email that data loading has been started
            user = get_user_by_id(SPUser, submission.submitting_user_id)
            send_email(to_email=user.email,
                       submission_status='analysis_ready_for_review',
                       recipient_name=user.name)
        finally:
            sftp_client.disconnect()

    finally:
        remove_lock_file(lock_file)
