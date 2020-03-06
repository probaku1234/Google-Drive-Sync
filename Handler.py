from watchdog.events import FileSystemEventHandler


class Handler(FileSystemEventHandler):
    def __init__(self, syncer):
        self.syncer = syncer

    def _get_file_name_and_id(self, file_path):
        """
        Get the file name, parent folder id, and index in file tree
        :param file_path: absolute path of file
        :returns: file name, parent file id, file's index in file tree
        """
        path = file_path
        path = path.replace(self.syncer.config['base_folder_dir'], '')
        path_list = path.split('\\')
        return path_list[-1], self.syncer.file_tree[len(path_list)-1].get(path_list[-2], None), len(path_list)-1

    def on_created(self, event):
        print("Received created event - %s." % event.src_path)
        file_name, folder_id, index = self._get_file_name_and_id(event.src_path)
        print(file_name, folder_id)

        if event.is_directory:
            if folder_id:
                new_folder_id = self.syncer.create_folder_in_drive(file_name, folder_id)
                self.syncer.file_tree[index][file_name] = new_folder_id
            else:
                print('Upload failed: target folder id is None')
        else:
            if folder_id:
                new_file_id = self.syncer.upload_file(file_name, event.src_path, folder_id)
                self.syncer.file_tree[index][file_name] = new_file_id
            else:
                print('Upload failed: target folder id is None')

    def on_modified(self, event):
        print("Received modified event - %s." % event.src_path)

    def on_moved(self, event):
        print("Received moved event - %s." % event.src_path)

    def on_deleted(self, event):
        print("Received deleted event - %s." % event.src_path)