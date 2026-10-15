import sys

import json

import argparse

from websocket import create_connection

 

def main():

    parser = argparse.ArgumentParser(description="WebSocket remote API tool")

    parser.add_argument("server", help="Server address")

    parser.add_argument("message", help="JSON message")

    args = parser.parse_args()

 

    ws = create_connection("ws://" + args.server)

    ws.send(args.message)

 

    while True:

        result = ws.recv()

        if result:

            message = json.loads(result)

            print(json.dumps(message, indent=2, ensure_ascii=False))

            if message.get("message") != "ready":

                break

 

    ws.close()

 

if __name__ == "__main__":

    main()