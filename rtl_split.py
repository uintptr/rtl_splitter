#!/usr/bin/env python3

import sys
import argparse
import asyncio

from asyncio import StreamReader, StreamWriter

from typing import Self

RTL_HEADER_SIZE = 12  # see struct rtl_tcp_info (sdr.c)
RTL_COMMAND_SIZE = 5 # see struct command (sdr.c)

class RTLSplitter:
    def __init__(self, host: str, port: int) -> None:

        self.host = host
        self.port = port

        self.client_writers: list[StreamWriter] = []

        self.header = b''

    async def __aenter__(self) -> Self:

        r,w = await asyncio.open_connection(self.host, self.port)
        self.reader = r
        self.writer = w

        self.header = await r.read(RTL_HEADER_SIZE)

        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None: # type: ignore

        self.writer.close()
        await self.writer.wait_closed()

    async def __rtl_proxy(self) -> None:

        while(True):

            data = await self.reader.read(1024)

            if data == b'':
                break

            for c in self.client_writers:
                try:
                    c.write(data)
                    await c.drain()
                except ConnectionResetError:
                    if c in self.client_writers:
                        self.client_writers.remove(c)
                except BrokenPipeError:
                    if c in self.client_writers:
                        self.client_writers.remove(c)

    async def send_command(self, cmd: bytes) -> None:
        self.writer.write(cmd)
        await self.writer.drain()

    def add_client(self, writer: StreamWriter) -> None:
        self.client_writers.append(writer)

    def rem_client(self, writer: StreamWriter) -> None:

        if writer in self.client_writers:
            self.client_writers.remove(writer)

    async def splitter(self) -> None:
        await self.__rtl_proxy()

class RTLClient:

    def __init__(self, rtl: RTLSplitter) -> None:
        self.rtl = rtl

    async def callback(self, reader: StreamReader, writer: StreamWriter) -> None:

        self.rtl.add_client(writer)

        try:
            writer.write(self.rtl.header)
            await writer.drain()

            while(True):
                data = await reader.read(5)

                if b'' == data:
                    break

                print("command", data.hex())

                await self.rtl.send_command(data)
        except asyncio.exceptions.CancelledError:
            pass
        finally:
            self.rtl.rem_client(writer)
            writer.close()
            await writer.wait_closed()

async def server_loop(rtl: RTLSplitter, port: int) -> None:

    client = RTLClient(rtl)

    server = await asyncio.start_server(client.callback, "0.0.0.0", port)

    async with server:
        await server.serve_forever()

async def main() -> int:

    status = 1

    parser = argparse.ArgumentParser()

    def_port = 1234
    def_target = "localhost"
    def_listening_port = 1234

    parser.add_argument("--target",
                        "-t",
                        type=str,
                        default=def_target,
                        help=f"rtl_tcp server address. Default:{def_target}")

    parser.add_argument("--port",
                        "-p",
                        type=int,
                        default=1234,
                        help=f"rtl_tcp server port. Default: {def_port}")

    parser.add_argument("--listen",
                        "-l",
                        type=int,
                        default=def_listening_port,
                        help=f"Listening. Default: {def_listening_port}")

    args = parser.parse_args()

    try:

        async with RTLSplitter(args.target, args.port) as rtl:

            await asyncio.gather(
                server_loop(rtl, args.listen),
                rtl.splitter()
            )

    except KeyboardInterrupt:
        status = 0

    return status


if __name__ == '__main__':

    status = asyncio.run(main())

    if 0 != status:
        sys.exit(status)