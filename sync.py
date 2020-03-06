import json
import io
from os import listdir, path
import os.path
import pickle
import time

from apiclient import errors
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from dateutil import parser
from collections import deque
from datetime import datetime
from tzlocal import get_localzone

from Handler import Handler


class GoogleDriveFolderSynchronizer:
    def __init__(self):
        """
        loads configuration from config.json and gets credential
        """
        with open('config.json', encoding='UTF-8') as json_data_file:
            self.config = json.load(json_data_file)
        self._get_credential()
        self.file_tree = [{}] * 100

    def _get_credential(self):
        """
        Get credential in order to use google drive api
        """
        creds = None

        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.config['SCOPES'])
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        self.service = build('drive', 'v3', credentials=creds)

    def _set_target_folder(self, folder_id, folder_name):
        """
        Set the target folder on drive for sync
        :param folder_id: the id of target folder
        :param folder_name: the name of target folder
        """
        print('target id: ' + folder_id)
        print('target name: ' + folder_name)
        self.config['target_folder_id'] = folder_id
        self.config['target_folder_name'] = folder_name
        with open('config.json', 'w', encoding='UTF-8') as json_data_file:
            json.dump(self.config, json_data_file)

    def get_list_all_folders(self):
        """
        Prints all folders in root folder on drive
        """
        results = self.service.files().list(q='"root" in parents and mimeType="application/vnd.google-apps.folder"',
                                            spaces='drive',
                                            pageSize=1000,
                                            fields="nextPageToken, files(id, name, kind)").execute()
        items = results.get('files', [])

        if not items:
            print('No folders found.')
        else:
            print('Files:')
            for index, item in enumerate(items):
                print(str(index + 1) + '. ' + item['name'])

            s = input('Choose target folder.')
            self._set_target_folder(items[int(s) - 1]['id'], items[int(s) - 1]['name'])

    @staticmethod
    def _change_time_format(time_string):
        """
        Changes the ISO time to datetime object
        :param time_string: ISO timestamp
        :return: datetime object
        """
        datetime_object = parser.isoparse(time_string)
        return datetime_object

    @staticmethod
    def _compare_times(drive_file_time, local_file_time):
        """
        Compares the local time and drive time.
        Since drive file time's timezone is not same as local time, the localization is required for comparing.
        :param drive_file_time: drive file's modified time
        :param local_file_time: local fie's modified time
        :return: 1 if drive file is greater than local time. -1 if drive file is less than local time. 0 if two are same.
        """
        local_time_zone = get_localzone()

        localized_drive_file_time = drive_file_time.astimezone(local_time_zone)
        localized_local_file_time = local_time_zone.localize(local_file_time)

        if localized_drive_file_time > localized_local_file_time:
            return 1
        elif localized_drive_file_time < localized_local_file_time:
            return -1
        else:
            return 0

    def _list_files_in_drive_folder(self, target_id):
        """
        Prints all files and folders in drive folder
        :param target_id: the id of target folder
        :return: dictionary of drive files : (key -> name of file, value -> (last modified time, id of file, name of file))
        list of drive folders name.
        """
        page_token = None
        while True:
            try:
                param = {}
                if page_token:
                    param['pageToken'] = page_token
                children = self.service.files().list(q='"' + target_id + '" in parents',
                                                     spaces='drive',
                                                     fields='files(id, name, mimeType, modifiedTime)').execute()

                drive_files_dict = {}
                drive_folders = []
                for child in children.get('files', []):
                    print(u'{0} ({1}) {2} {3}'.format(child['mimeType'], child['name'], child['id'],
                                                      child['modifiedTime']))
                    if child['mimeType'] == 'application/vnd.google-apps.folder':
                        drive_folders.append((child['id'], child['name']))
                    else:
                        drive_files_dict[child['name']] = (
                        self._change_time_format(child['modifiedTime']), child['id'], child['name'])

                page_token = children.get('nextPageToken')
                if not page_token:
                    return drive_folders, drive_files_dict
            except errors.HttpError as error:
                print('An error occurred: %s' % error)
                return None, None

    def _download_file(self, file_id, file_name, path):
        """
        Download the file on drive.
        :param file_id: the id of target file
        :param file_name: the name of target file
        :param path: the local path for downloading
        """
        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(path + file_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        print('Start download ' + file_name)
        while not done:
            status, done = downloader.next_chunk()
            print("Download %d%%." % int(status.progress() * 100))

    def upload_file(self, file_name, file_path, target_folder_id):
        """
        Upload file to drive
        :param file_name: the name of target file
        :param file_path: the local path of target file
        :param target_folder_id: the id of parent folder of target file
        :return: created file's id
        """
        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id]
        }
        media = MediaFileUpload(file_path + file_name, resumable=True)
        file = self.service.files().create(body=file_metadata,
                                           media_body=media,
                                           fields='id').execute()
        print('File ID: %s' % file.get('id'))
        return file.get('id')

    def _update_file(self, file_id, file_name, path):
        """
        Update content of existing file on drive
        :param file_id: the id of target file
        :param file_name: the name of target file
        :param path: the local path of target file
        :return: True if success, False if fail
        """
        try:
            file = self.service.files().get(fileId=file_id).execute()
            del file['id']
            media_body = MediaFileUpload(path + file_name, resumable=True)

            updated_file = self.service.files().update(
                fileId=file_id,
                body=file,
                media_body=media_body
            ).execute()
            print('Updating file %s completed' % file_name)
            return True
        except errors.HttpError as error:
            print('An error occurred: %s' % error)
            return False

    def _get_file_content(self, file_id):
        try:
            return self.service.files().get_media(fileId=file_id).execute()
        except errors.HttpError as error:
            print('An error occurred: %s' % error)
            return None

    def create_folder_in_drive(self, folder_name, parent_folder_id):
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        file = self.service.files().create(body=file_metadata,
                                           fields='id').execute()
        return file.get('id')

    def BFS(self, queue):
        if not queue:
            return

        folder = queue.popleft()
        self.file_tree[folder[3]][folder[1]] = folder[0]

        drive_folders, drive_files_dict = self._list_files_in_drive_folder(folder[0])

        # if there is folder, insert folder to queue
        if drive_folders:
            for drive_folder in drive_folders:
                temp = list(drive_folder)
                temp.append(folder[2] + drive_folder[1] + '\\')
                temp.append(folder[3] + 1)
                queue.append(tuple(temp))

        if drive_files_dict:
            next_path = folder[2]

            # check if the directory exist
            if path.exists(next_path):
                local_files = []
                local_folders = []

                # get all files and folders in current path
                for f in listdir(next_path):
                    if os.path.isfile(os.path.join(next_path, f)):
                        local_files.append(f)
                    else:
                        local_folders.append(f)

                if local_files:
                    local_files_dict = {}

                    # get last modified time of local files
                    for local_file in local_files:
                        datetime_object = datetime.fromtimestamp(os.path.getmtime(next_path + local_file))
                        local_files_dict[local_file] = datetime_object

                    local_files_set = set(local_files_dict.keys())
                    drive_files_set = set(drive_files_dict.keys())

                    for key, value in drive_files_dict.items():
                        self.file_tree[folder[3] + 1][key] = value[1]
                        if key in local_files_set:
                            # if drive file's time is greater than local file's time, download file
                            # else update file on drive
                            if self._compare_times(value[0], local_files_dict[key]):
                                if self._get_file_content(value[1]) != b'':
                                    self._download_file(value[1], value[2], next_path)
                            else:
                                self._update_file(value[1], value[2], next_path)

                    # upload all files that not exist on drive but exist on local
                    for local_file in local_files_set.difference(drive_files_set):
                        self.file_tree[folder[3] + 1][local_file] = self.upload_file(local_file, next_path, folder[0])
                else:  # if file not exist in local, download all files on drive
                    for drive_file in drive_files_dict.values():
                        if self._get_file_content(drive_file[1]) != b'':
                            self._download_file(drive_file[1], drive_file[2], next_path)
            else:  # if directory doesn't exist, create the directory and download all files
                try:
                    os.mkdir(next_path)
                    for drive_file in drive_files_dict.values():
                        if self._get_file_content(drive_file[1]) != b'':
                            self._download_file(drive_file[1], drive_file[2], next_path)
                except OSError:
                    print("Creation of the directory %s failed" % next_path)

        self.BFS(queue)

    def sync(self):
        """
        Syncs drive folder and local folder
        """
        if self.config['target_folder_id'] == '':
            self.get_list_all_folders()

        # Use queue to travers all folders in file tree
        queue = deque([(self.config['target_folder_id'], self.config['target_folder_name'],
                        self.config['base_folder_dir'] + self.config['target_folder_name'] + '\\', 0)])

        self.BFS(queue)


class Watcher:
    def __init__(self, syncer):
        self.observer = Observer()
        self.syncer = syncer

    def run(self):
        event_handler = Handler(self.syncer)
        self.observer.schedule(event_handler,
                               self.syncer.config['base_folder_dir'] + self.syncer.config['target_folder_name'],
                               recursive=True)
        self.observer.start()

        try:
            while True:
                time.sleep(5)
        except Exception as error:
            self.observer.stop()
            print(error)


if __name__ == '__main__':
    synchronizer = GoogleDriveFolderSynchronizer()
    #synchronizer.sync()
    watcher = Watcher(synchronizer)
    watcher.run()
