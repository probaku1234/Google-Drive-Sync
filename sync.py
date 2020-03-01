import json
import io
from os import listdir, path
import os.path
import pickle

from apiclient import errors
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from dateutil import parser
from collections import deque
from datetime import datetime
from tzlocal import get_localzone


class GoogleDriveFolderSynchronizer:
    def __init__(self):
        with open('config.json', encoding='UTF-8') as json_data_file:
            self.config = json.load(json_data_file)
        self._get_credential()

    def _get_credential(self):
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
        print('target id: ' + folder_id)
        print('target name: ' + folder_name)
        self.config['target_folder_id'] = folder_id
        self.config['target_folder_name'] = folder_name
        with open('config.json', 'w', encoding='UTF-8') as json_data_file:
            json.dump(self.config, json_data_file)

    def get_list_all_folders(self):
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
            self._set_target_folder(items[int(s)-1]['id'], items[int(s)-1]['name'])

    def _change_time_format(self, time_string):
        datetime_object = parser.isoparse(time_string)
        return datetime_object

    def _compare_times(self, drive_file_time, local_file_time):
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
                    print(u'{0} ({1}) {2} {3}'.format(child['mimeType'], child['name'], child['id'], child['modifiedTime']))
                    if child['mimeType'] == 'application/vnd.google-apps.folder':
                        drive_folders.append((child['id'], child['name']))
                    else:
                        drive_files_dict[child['name']] = (self._change_time_format(child['modifiedTime']), child['id'], child['name'])

                page_token = children.get('nextPageToken')
                if not page_token:
                    return drive_folders, drive_files_dict
            except errors.HttpError as error:
                print('An error occurred: %s' % error)
                return None, None

    def _download_file(self, file_id, file_name, path):
        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(path + file_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        print('Start download ' + file_name)
        while not done:
            status, done = downloader.next_chunk()
            print("Download %d%%." % int(status.progress() * 100))

    def _upload_file(self, file_name, file_path, target_folder_id):
        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id]
        }
        media = MediaFileUpload(file_path + file_name, resumable=True)
        file = self.service.files().create(body=file_metadata,
                                           media_body=media,
                                           fields='id').execute()
        print('File ID: %s' % file.get('id'))

    def _update_file(self, file_id, file_name, path):
        try:
            file = self.service.files().get(fileId=file_id).execute()
            del file['id']
            media_body = MediaFileUpload(path+file_name, resumable=True)

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

    def sync(self):
        if self.config['target_folder_id'] == '':
            self.get_list_all_folders()

        queue = deque([(self.config['target_folder_id'], self.config['target_folder_name'])])
        current_path = self.config['base_folder_dir']

        while queue:
            folder = queue.popleft()

            drive_folders, drive_files_dict = self._list_files_in_drive_folder(folder[0])

            if drive_folders:
                for drive_folder in drive_folders:
                    queue.append(drive_folder)

            if drive_files_dict:
                current_path += folder[1] + '\\'

                if path.exists(current_path):
                    local_files = []
                    local_folders = []

                    for f in listdir(current_path):
                        if os.path.isfile(os.path.join(current_path, f)):
                            local_files.append(f)
                        else:
                            local_folders.append(f)

                    if local_files:
                        local_files_dict = {}

                        for local_file in local_files:
                            datetime_object = datetime.fromtimestamp(os.path.getmtime(current_path + local_file))
                            local_files_dict[local_file] = datetime_object

                        local_files_set = set(local_files_dict.keys())
                        drive_files_set = set(drive_files_dict.keys())

                        for key, value in drive_files_dict.items():
                            if key in local_files_set:
                                if self._compare_times(value[0], local_files_dict[key]):
                                    self._download_file(value[1], value[2], current_path)
                                else:
                                    self._update_file(value[1], value[2], current_path)

                        for local_file in local_files_set.difference(drive_files_set):
                            self._upload_file(local_file, current_path, folder[0])
                    else:
                        for drive_file in drive_files_dict.values():
                            self._download_file(drive_file[1], drive_file[2], current_path)
                else:
                    try:
                        os.mkdir(current_path)
                        for drive_file in drive_files_dict.values():
                            self._download_file(drive_file[1], drive_file[2], current_path)
                    except OSError:
                        print("Creation of the directory %s failed" % current_path)


if __name__ == '__main__':
    print(get_localzone())
    synchronizer = GoogleDriveFolderSynchronizer()
    synchronizer.sync()
