# Google-Drive-Sync
Google Drive Sync with local folder using Google Drive Api v3. 
Only works on Windows.

## Installation
### Step 1: Turn on the Drive API
1. Go to the [link](https://developers.google.com/drive/api/v3/quickstart/python#step_1_turn_on_the). <br>
2. Click the button to create a new Cloud Platform project and automatically enable the Drive API. <br>
3. In resulting dialog click `DOWNLOAD CLIENT CONFIGURATION` and save the file `credentials.json` to the root folder. <br>

### Step 2: Set configuration
Open `config.json` and edit the value of `base_folder_dir` as the directory that you want to make folder for sync. (Example: "base_folder_dir": "C:\\pikapika\\")<br>
### Step 3: Install requirements
Run command on terminal `pip install -r requirements.txt`.

## Run application
Run `sync.py`
