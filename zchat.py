#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import threading
import asyncio
import re
import sqlite3
import requests
import signal
from datetime import datetime
from os.path import dirname, exists

import tornado.ioloop
import tornado.web
import tornado.websocket
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver
from websocket import create_connection

# ==== 設定ファイルパス ====
base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
file_name_param = "zchat_param.json"
file_name_gate = "gates.tab"
file_name_pre = "zchat_page_pre.html"
file_name_post = "zchat_page_post.html"
file_name_athletes = "riders.sqlite"
path_param = os.path.join(base_path, file_name_param)
path_gate = os.path.join(base_path, file_name_gate)
path_pre = os.path.join(base_path, file_name_pre)
path_post = os.path.join(base_path, file_name_post)
path_athletes = os.path.join(base_path, file_name_athletes)
path_static = os.path.join(base_path, "static")

# ==== クライアント保持 ====
clients = []

# グローバル変数でトークン管理
token_info = {
    "access_token": None,
    "refresh_token": None,
    "expires_in": 3600  # デフォルト1時間
}

# ==== WebSocket Server ====
class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        print("WebSocket Open")
        if self not in clients:
            clients.append(self)

    def on_message(self, message):
        print("WebSocket on_message:", message)
        for client in clients:
            try:
                client.write_message(message)
            except:
                print("Error: WebSocket Sending")

    def on_close(self):
        print("WeWebSocket on_close")
        if self in clients:
            clients.remove(self)

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        try:
            self.render(path_post)
        except Exception as e:
            self.write(f"Error: MainHandler: {str(e)}")

class faviconHandler(tornado.web.RequestHandler):
    def get(self):
        try:
            self.render(path_favicon)
        except Exception as e:
            self.write(f"Error: MainHandler: {str(e)}")

class NoneHandler(tornado.web.RequestHandler):
    def get(self):
        try:
            self.render("")
        except Exception as e:
            self.write(f"Error: MainHandler: {str(e)}")

def start_websocket_server(zchat_param):
    if not os.path.exists(path_pre):
        print(f"Error: '{path_pre}' not found.")
        sys.exit(1)

    try:
        with open(path_pre, encoding="utf-8") as f:
            html_data = f.read()
        html_data = html_data.replace("===OpenAI_key===", zchat_param["OpenAI_key"])
        html_data = html_data.replace("===LANGUAGE===", zchat_param["Language"])
        with open(path_post, mode="w", encoding="utf-8") as f:
            f.write(html_data)
    except Exception as e:
        print(f"Error: Cannot make post_html: {str(e)}")
        sys.exit(1)
    
    settings = {
        "static_path": path_static,
    }    

    app = tornado.web.Application([
        (r"/", MainHandler),
        (r"/websocket", WebSocketHandler),
        (r"/None", NoneHandler),
        (r"/(favicon.ico)", tornado.web.StaticFileHandler)
        
    ],**settings)

    try:
        app.listen(zchat_param["sv_port"])
        print(f"Server running (port: {zchat_param['sv_port']})")
        tornado.ioloop.IOLoop.current().start()
    except Exception as e:
        print(f"Error: Cannot open port: {str(e)}")
        sys.exit(1)

# CTRL+C で停止したら、ブラウザを閉じて終了
def handler(signal, frame):
	print('quit')
	# ブラウザ停止
	sys.exit(0)

# ==== ログ監視処理 ====
class TailHandler(FileSystemEventHandler):
    def __init__(self, log_path):
        self.log_path = zchat_param["log_path"]
        self.file = open(zchat_param["log_path"], 'rb')
        self.pos = os.stat(zchat_param["log_path"])[6]
        self.idLeader = "0"
        self.idMe = zchat_param["zwift_id"]
        self.isInChat = 0
        self.gates = {}
        self.tiEventStart = datetime.strptime("0:0:0", '%H:%M:%S')
        self.messageID = 0
        self.itemID = 0

    def close(self):
        try:
            self.file.close()
        except:
            pass

    def get_rider(self, id):
        data = {}
        data["id"] = id
        data["fullname"] = None
        data["countryCode"] = None
        data["avatar"] = None
        data["weight"] = None
        data["gender"] = None
        data["age"] = None
        data["level"] = None
        data["powerMeter"] = None
        data["ftp"] = None
        data["racingScore"] = None
        data["updatetime"] = None

        self.sqlite_conn = sqlite3.connect(path_athletes)
        self.sqlite_cur = self.sqlite_conn.cursor()

        # self.sqlite_cur.execute("SELECT id, data FROM athletes WHERE id = {zid}".format(zid=id))
        res = self.sqlite_cur.execute("SELECT id, data FROM athletes WHERE id = {zid}".format(zid=id))
        row = res.fetchone()

        self.sqlite_cur.close()
        self.sqlite_conn.close()

        # DB になければ、Zwift API から入手する
        if(row == None):
            data = self.get_rider_from_api(id)
            return data

        #row = self.sqlite_cur.fetchone()
        # DB あるがレコードが古ければ、Zwift API から入手する
        if(row != None):
            if(row[1] != None):
                data = json.loads(row[1])
                return data
        return data

    # Zwift API から Profile 取得
    def get_rider_from_api(self, id):
        data = {}
        data["id"] = id
        data["fullname"] = None
        data["countryCode"] = None
        data["avatar"] = None
        data["weight"] = None
        data["gender"] = None
        data["age"] = None
        data["level"] = None
        data["powerMeter"] = None
        data["ftp"] = None
        data["racingScore"] = None
        data["updatetime"] = time.time()
        url = "https://us-or-rly101.zwift.com/api/profiles/" + id
        
        payload = {
        }
        headers = {
            "Authorization": "Bearer " + token_info["access_token"],
            "accept": "application/json",
            "Connection": "keep-alive",
            "noAuth": "true",
            "Host": "us-or-rly101.zwift.com"
        }
        
        response = requests.get(url, data=payload, headers=headers, verify=False)

        # 結果の表示
        if response.status_code == 200:
            api_data = {}
            api_data["powerMeter"] = None
            api_data["ftp"] = None
            api_data["competitionMetrics"] = {}
            api_data["competitionMetrics"]["racingScore"] = None
            api_data = response.json()
            data["fullname"] = api_data["firstName"] + " " + api_data["lastName"]
            data["countryCode"] = api_data["countryCode"]
            data["avatar"] = api_data["imageSrc"]
            data["weight"] = (api_data["weight"]/1000)
            if(api_data["male"]):
                data["gender"] = "male"
            else:
                data["gender"] = "female"
            data["age"] = api_data["age"]
            data["level"] = (api_data["achievementLevel"]/100)
            if("powerMeter" in api_data):
                data["powerMeter"] = api_data["powerSourceModel"]
            if("ftp" in api_data):
                data["ftp"] = api_data["ftp"]
            if api_data.get("competitionMetrics"):
                if("racingScore" in api_data["competitionMetrics"]):
                    data["racingScore"] = api_data["competitionMetrics"]["racingScore"]
                else:
                    data["racingScore"] = None
            self.sqlite_conn = sqlite3.connect(path_athletes)
            self.sqlite_cur = self.sqlite_conn.cursor()

            # self.sqlite_cur.execute("SELECT id, data FROM athletes WHERE id = {zid}".format(zid=id))
            json_data = json.dumps(data)
            res = self.sqlite_cur.execute("INSERT OR REPLACE INTO athletes (id, data) VALUES (?, ?)",(id, json_data))
            
            self.sqlite_conn.commit()
            self.sqlite_cur.close()
            self.sqlite_conn.close()

            print("get rider_data from API: ", data["fullname"])
        else:
            print("Failed to get rider_data from API:", response.status_code)
            print(response.text)

        return data

    # Gate file を書き込む
    def subWriteGates(self):
        with open(path_gate, mode='w', encoding="utf-8") as f:
            cnt = 0
            for gatename in self.gates :
                try:
                    f.write(gatename + "\t" + self.gates[gatename]["lasttime"] + "\t" + self.gates[gatename]["passtime"] + "\n")
                except UnicodeDecodeError as e:
                    print("=== Exception >>>")
                    print(e)
                    print("<<< Exception ===")
                    return None
                cnt = cnt + 1
            f.close()

    def send_message(self, message):
        print (message)
        itemTag = "itemTag_%d" %self.itemID
        self.itemID = self.itemID + 1
        message = "<span id='" + itemTag + "'>" + message + "</br></span>"
        ws = create_connection("ws://{sv_ip}:{sv_port}/websocket".format( 
                        sv_ip="127.0.0.1", 
                        sv_port=zchat_param["sv_port"]))
        ws.send(message)
        ws.recv()
        ws.close()


    def on_modified(self, event):
        if not event.is_directory and event.src_path == self.log_path:
            self.read_new_lines()

    def read_new_lines(self):
        if(os.path.getsize(zchat_param["log_path"]) < self.pos):
            self.file.seek(0)
        #for line in iter(lambda: self.read_one_line(), ''):
        for i, line in enumerate(self.file, 1):
            decoded = False
            for encoding in ['utf-8', 'shift_jis', 'cp932']:
                try:
                    decoded_line = line.decode(encoding)
                    decoded = True
                    line = decoded_line
                    break
                except UnicodeDecodeError:
                    continue
            if(decoded == False):
                print(f"Decode failure {line[:30]}...")
                continue
            if(line == None):
                continue
            if(line == "\n"):
                continue
            if(line == "\r\n"):
                continue
            if (line.find("GroupEvents: Started event")>0):
                # スタート時刻
                #pos1 = line.find('GroupEvents')
                #stime = line[1:pos1 - 2]
                pos1 = line.find(']')
                stime = line[1:pos1-1]

                self.tiEventStart = datetime.strptime(stime, '%H:%M:%S')
                self.send_message ("<font color=aa00aa>▲∩▲Event Start: " + self.tiEventStart.strftime('%H:%M:%S') + "</font>\n")
                
                # イベント開始したので、ゲート情報は初期化
                self.gates = {}
                self.gates["eventstart"] = {}
                self.gates["eventstart"]["lasttime"] = stime;
                self.gates["eventstart"]["passtime"] = ""

                self.subWriteGates()

            if (line.find("TimingArch: hit finish line for ") > 0 and len(line) > 43):
                # ゲート通過
                pos1 = line.find(']')
                stime = line[1:pos1-1]
                tiPassGate = datetime.strptime(stime, '%H:%M:%S')
                pos1 = line.find('TimingArch')
                pos2 = pos1 + 32

                strGateName = line[pos2:][:-1]

                if(strGateName in self.gates):
                    # 2回目移行のゲート通過
                    # 前回ゲートとの差分
                    tiLastTime = datetime.strptime(self.gates[strGateName]["lasttime"], '%H:%M:%S')
                    secInterval = tiPassGate - tiLastTime
                    strInterval = ("%02d:%02d" % (int(secInterval.seconds/60), secInterval.seconds%60 ))
                    self.gates[strGateName]["passtime"]    = self.gates[strGateName]["passtime"] + " - " + strInterval

                    targetID = "targetID_%d" %self.messageID
                    strMessage = "<button onclick=\"copyToClipboard('" + targetID + "')\">-</button><code id='" + targetID + "'>" + strGateName + self.gates[strGateName]["passtime"] + "</code>"
                    self.messageID = self.messageID + 1

                    # self.send_message ("<font color=aa00aa>▲∩▲" + strGateName + self.gates[strGateName]["passtime"] + "</font>\n")
                    self.send_message ("<font color=aa00aa>▲∩▲" + strMessage + "</font>\n")
                else:
                    # 初ゲート通過
                    self.gates[strGateName] = {}
                    # Lead-in (スタートとの差分)
                    secInterval = tiPassGate - self.tiEventStart
                    strInterval = ("%02d:%02d" % (int(secInterval.seconds/60), secInterval.seconds%60 ))
                    self.gates[strGateName]["passtime"]    = " Lead-in(" + strInterval + ") "

                    targetID = "targetID_%d" %self.messageID
                    strMessage = "<button onclick=\"copyToClipboard('" + targetID + "')\">-</button><code id='" + targetID + "'>" + strGateName + self.gates[strGateName]["passtime"] + "</code>"
                    self.messageID = self.messageID + 1

#                    self.send_message ("<font color=aa00aa>▲∩▲" + strGateName + self.gates[strGateName]["passtime"] + "</font>\n")
                    self.send_message ("<font color=aa00aa>▲∩▲" + strMessage + "</font>\n")
                    self.gates[strGateName]["passtime"]= self.gates[strGateName]["passtime"] + ", Lap time"
                # ゲート通過時刻 の保存 (イベント中に Riders ファイルをよく書き換えて再起動するので)
                self.gates[strGateName]["lasttime"] = stime
                
                self.subWriteGates();
            
            
            if (line[0:1] != '['):
                # 時刻がない行は、前行の継続
                if (self.isInChat == 1):
                    # 前行からの Chat の継続なら、表示する
                    targetID = "targetID_%d" %self.messageID
                    message = "<button onclick=\"copyToClipboard('" + targetID + "')\">-</button><code id='" + targetID + "'>" + line + "</code>"

                    self.messageID = self.messageID + 1

                    self.send_message(message)
            else:
                self.isInChat = 0

            if ('Chat:' in line):
                self.isInChat = 1;
                # Chat 行
                # "Chat: " 〜 "): " までを抽出する
                pos1 = line.find('Chat: ')
                stime = line[0:(pos1 - 1)]
                pos2 = line.find('): ')
                message = line[(pos2 + 3):(len(line) - 1)]
                text = line[pos1 + 6 : pos2 - 5]
                #(Leader - in paddock): ならライドリーダー
                if(line.find('(Leader - in paddock') > 0):
                    isLeader = 1
                else:
                    isLeader = 0

                # (Private): ならPrivate Message
                isPrivate = 0
                if(line.find('(Private):') > 0):
                    isPrivate = 1

                # 最後の " (" 以降を削る
                pos2 = text.rfind(" (")
                text = text[0:pos2]
                # 最後の " " までが ID
                pos2 = text.rfind(' ')
                logname = ""
                if(pos2 >= 0):
                    # ID のみではない
                    logname = text[0:pos2]
                    id = text[pos2 + 1:(len(text) + 1)]
                else: 
                    id = text
                    name = ""

                if(isLeader):
                    # ライドリーダーの id を保存
                    self.idLeader = id

                # riders にある id なら名前を置換
                rider_data = self.get_rider(id)
                if(rider_data != None and rider_data["fullname"] != None and rider_data["fullname"] != ""):
                    name = rider_data["fullname"]
                elif(logname != ""):
                    name = logname
                else:
                    name = id
                
                targetID = "targetID_%d" %self.messageID

                # 重要文字列の置換
                target = re.compile(r'help', re.IGNORECASE)
                message = re.sub(target, '<font color=ff0000>HELP</font>', message)
                target = re.compile(r'{my_name}'.format(my_name=zchat_param["my_name"]), re.IGNORECASE)
                message = re.sub(target, '<font color=4444ff>' + zchat_param["my_name"] + '</font>', message)
                if("avatar" in rider_data):
                    message = "<img src=\"{avatar}\" width=20 height=20 onclick=\"copyToClipboard('{targetID}')\"><code id='{targetID}'> {message}</code>".format(avatar=rider_data["avatar"],targetID=targetID,message=message)
                else:
                    message = "<button onclick=\"copyToClipboard('{targetID}')\">-</button><code id='{targetID}'> {message}</code>".format(targetID=targetID,message=message)

                # 名前等
                message_line = "<font color=888888 size=-1><a href='https://www.zwift.com/ja/athlete/" + id + "' target=_new>" + stime + "</a> " ;
                message_line = message_line + "<a onclick=\"translateText('{targetID}')\">■■ </a>".format(targetID=targetID,message=message);
                if("weight" in rider_data and rider_data["weight"] != None):
                    if("gender" in rider_data and rider_data["gender"] == "female"):
                        message_line = message_line + "<font color=ff8888>{name}</font>".format(name=name)
                    else:
                        message_line = message_line + name
                    message_line = message_line + " : <font color=bbbbbb>"
                    if("ftp" in rider_data):
                        message_line = message_line + "ftp({ftp})".format(ftp=round(rider_data["ftp"]/rider_data["weight"],1))
                    if rider_data.get("racingScore"):
                        message_line = message_line + " : rs({racingScore})".format(racingScore=round(rider_data["racingScore"]))
                    message_line = message_line + " : </font>"

                else:
                    message_line = message_line + name + " : "
                message_line = message_line + "</br></font><b>" + message + "</B>\n"

                if(isPrivate):
                    # Privateの発言
                    message_line = "<font color=#ff0000>" + message_line + "</font>"
                elif(id == self.idMe):
                    # 自分の発言
                    message_line = "<font color=#0000ff>" + message_line + "</font>"
                elif(id == self.idLeader):
                    # ライドリーダーの発言
                    message_line = "<font color=#888800>" + message_line + "</font>"

                self.messageID = self.messageID + 1

                self.send_message(message_line)

                # Rider データが古ければ更新しておく
                if(rider_data["updatetime"] < time.time()-(3600*5)):
                    self.get_rider_from_api(id)

        self.pos = self.file.tell()

def zwift_api_login():
    url = "https://secure.zwift.com/auth/realms/zwift/protocol/openid-connect/token"
    
    payload = {
        "client_id" : "Zwift Game Client",
        "username" : zchat_param["zwift_email"],
        "password" : zchat_param["zwift_password"],
        "grant_type" : "password"
    }
    headers = {
        "accept": "*/*",
        "Connection": "keep-alive",
        "noAuth": "true",
        "Host": "secure.zwift.com",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    response = requests.post(url, data=payload, headers=headers, verify=False)

    # 結果の表示
    if response.status_code == 200:
        token_data = response.json()
        #print("Access Token:", token_data["access_token"])
        update_token_info(response.json())
    else:
        print("Failed to get token:", response.status_code)
        print(response.text)

# リフレッシュトークンを使ってトークン更新
def refresh_token():
    print("[INFO] Refreshing token...")
    data = {
        "client_id": "Zwift Game Client",
        "grant_type": "refresh_token",
        "refresh_token": token_info["refresh_token"]
    }
    headers = {
        "accept": "*/*",
        "Connection": "keep-alive",
        "noAuth": "true",
        "User-Agent": "CNL/3.44.0 (Darwin Kernel 23.2.0) zwift/1.0.122968 game/1.54.0 curl/8.4.0",
        "Platform": "OSX",
        "Source": "Game Client",
        "Host": "secure.zwift.com",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    TOKEN_URL = "https://secure.zwift.com/auth/realms/zwift/protocol/openid-connect/token"
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    if response.status_code == 200:
        update_token_info(response.json())
    else:
        print("Failed to refresh token:", response.status_code)
        print(response.text)

# トークン情報の更新と次回リフレッシュのスケジュール
def update_token_info(data):
    token_info["access_token"] = data["access_token"]
    token_info["refresh_token"] = data["refresh_token"]
    token_info["expires_in"] = data["expires_in"]
    print("[OK] Access Token Updated")
    print("Access Token (short):", token_info["access_token"][:20], "...")

    # 次回リフレッシュタイミング（例：90%の時間経過で更新）
    refresh_in = int(token_info["expires_in"] * 0.9)
    t = threading.Timer(refresh_in, refresh_token)
    t.daemon = True
    t.start()
    print(f"[TIMER] Next token refresh scheduled in {refresh_in} seconds")


def start_log_watcher(log_path):
    observer = PollingObserver()
    handler = TailHandler(log_path)
    observer.schedule(handler, dirname(log_path))
    observer.start()
    print("Starting Log observer:", log_path)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    finally:
        handler.close()
        observer.join()

# ==== 設定読み込み ====
def read_param():
    try:
        with open(path_param, 'r', encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Error: Cannot open param file. ", e)
        sys.exit(1)

# ==== メイン実行 ====
if __name__ == "__main__":
    zchat_param = read_param()
    zchat_param["zwift_id"] = str(zchat_param["zwift_id"])
    log_path = zchat_param.get("log_path")
    if not log_path or not os.path.exists(log_path):
        print(f"Error: Cannot open Log File: {log_path}")
        sys.exit(1)

	# CTRL+C をキャッチ
    signal.signal(signal.SIGINT, handler)

    zwift_api_login()

    # スレッドでログ監視を別実行
    t = threading.Thread(target=start_log_watcher, args=(log_path,), daemon=True)
    t.start()

    # メインスレッドでWebSocketサーバー実行
    start_websocket_server(zchat_param)
