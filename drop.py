#!/usr/bin/env python

import sys
import os
import dropbox
import subprocess
import requests
import json
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError, AuthError
from IPython import embed
import yaml

class Config(object):
    def __init__(self):
        self.homedir = os.path.expanduser("~")
        self.our_dir = os.path.join(self.homedir, ".dropblame")
        self.config_path = os.path.join(self.our_dir, "config.yml")
        self.storage_dir = os.path.join(self.our_dir, "storage")
        self.dropbox_dir = None
        self.token = None

        if not os.path.exists(self.config_path):
            print("Creating new config file at ~/.dropblame/config.yml")
            if not os.path.exists(self.our_dir):
                os.makedirs(self.our_dir)
            self.save_config()

        self.load_config()

    def read_token(self):
        print("To link this to Dropbox, you will first need to generate an access token: https://blogs.dropbox.com/developers/2014/05/generate-an-access-token-for-your-own-account/")
        while self.token is None:
            token = raw_input("Enter your token here: ").strip()
            if token == '':
                continue
            print("Testing your token now...")

            dbx = dropbox.Dropbox(token)
            try:
                dbx.users_get_current_account()
            except AuthError:
                print("ERROR: Invalid access token. Please try again!")
                continue

            print("Token looks good, thanks!")
            self.token = token
        self.save_config()

    def load_config(self):
        data = {}
        with open(self.config_path, 'r') as f:
            data = yaml.load(f.read())

        if 'dropbox_dir' in data:
            self.dropbox_dir = data['dropbox_dir']
        else:
            path = raw_input("Please enter the path to your Dropbox directory (default: ~/Dropbox): ").strip()
            if path == '':
                path = "~/Dropbox"
            self.dropbox_dir = os.path.expanduser(path)
            self.save_config()

        if 'token' in data:
            self.token = data['token']
        else:
            self.read_token()

    def save_config(self):
        data = {}
        if self.dropbox_dir is not None:
            data['dropbox_dir'] = self.dropbox_dir
        if self.token is not None:
            data['token'] = self.token

        yaml_text = yaml.dump(data, default_flow_style=False)
        with open(self.config_path, 'w') as f:
            f.write(yaml_text)


def cmd(line, cwd=None):
    p = subprocess.Popen(line, shell=True, cwd=cwd, stdout=subprocess.PIPE)
    return p.communicate()[0]

# Convert the revision history of a given file into a git repository
def sync_repo(filepath):
    basename = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, os.path.realpath(config.dropbox_dir))
    gitdir = os.path.join(config.storage_dir, relpath)
    if not os.path.exists(gitdir):
        os.makedirs(gitdir)

    revs = [entry.rev for entry in dbx.files_list_revisions("/"+relpath, limit=100).entries]
    revs.reverse()

    current_revs = []
    if os.path.exists(os.path.join(gitdir, ".git")):
        current_revs = cmd("git log --format=%B", gitdir).split()
    else:
        cmd("git init", gitdir)


    # As we find more user ids who contributed to the file, we
    # request and cache their info here
    userinfo = {}

    missing_revs = [rev for rev in revs if rev not in current_revs]

    if len(missing_revs) > 0:
        print("Found {0} revisions to download".format(len(missing_revs)))

    i = 0
    for rev in missing_revs:
        i += 1
        localpath = os.path.join(gitdir, basename)
        revpath = "rev:{0}".format(rev)
        print("{0}/{1} Fetching revision {2}".format(i, len(missing_revs), rev))
        r = requests.post(
            "https://api.dropboxapi.com/2/files/get_metadata",
            headers={'Authorization': "Bearer {0}".format(config.token),
                     'Content-Type': "application/json"},
            data=json.dumps({'path': revpath}))
        meta = json.loads(r.text)

        author_name = "You"
        if 'sharing_info' in meta:
            author_id = meta['sharing_info']['modified_by']
            if author_id not in userinfo:
                userinfo[author_id] = dbx.users_get_account(author_id)
            author_name = userinfo[author_id].name.display_name

        dbx.files_download_to_file(localpath, revpath)
        cmd("git add -A . && git commit -m {0} --author=\"{1} <mystery@example.org>\" --date=\"{2}\"".format(rev, author_name, meta['client_modified']), gitdir)

    return gitdir

if __name__ == '__main__':
    config = Config()
    dbx = dropbox.Dropbox(config.token)

    path = os.path.abspath(sys.argv[2])
    gitdir = sync_repo(path)
    p = subprocess.Popen("git blame {0}".format(os.path.basename(path)),
                         shell=True, cwd=gitdir)
    p.wait()
