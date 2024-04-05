#!/usr/bin/env python3

import sys
import argparse
import asyncio
import enum
import struct

from asyncio import StreamReader, StreamWriter

from typing import Self

RTL_HEADER_SIZE = 12  # see struct rtl_tcp_info (sdr.c)
RTL_COMMAND_SIZE = 5  # see struct command (sdr.c)


class RTLCommand(enum.Enum):
    RTLTCP_SET_FREQ = 0x01
    RTLTCP_SET_SAMPLE_RATE = 0x02
    RTLTCP_SET_GAIN_MODE = 0x03
    RTLTCP_SET_GAIN = 0x04
    RTLTCP_SET_FREQ_CORRECTION = 0x05
    RTLTCP_SET_IF_TUNER_GAIN = 0x06
    RTLTCP_SET_TEST_MODE = 0x07
    RTLTCP_SET_AGC_MODE = 0x08
    RTLTCP_SET_DIRECT_SAMPLING = 0x09
    RTLTCP_SET_OFFSET_TUNING = 0x0a
    RTLTCP_SET_RTL_XTAL = 0x0b
    RTLTCP_SET_TUNER_XTAL = 0x0c
    RTLTCP_SET_TUNER_GAIN_BY_ID = 0x0d
    RTLTCP_SET_BIAS_TEE = 0x0e


class RTLSplitter:
    def __init__(self, host: str, port: int) -> None:

        self.host = host
        self.port = port

        self.client_writers: list[StreamWriter] = []

        self.header = b''

    async def __aenter__(self) -> Self:

        r, w = await asyncio.open_connection(self.host, self.port)
        self.reader = r
        self.writer = w

        self.header = await r.read(RTL_HEADER_SIZE)

        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:  # type: ignore

        self.writer.close()
        await self.writer.wait_closed()

    async def send_command(self, cmd: bytes) -> None:
        self.writer.write(cmd)
        await self.writer.drain()

    def add_client(self, writer: StreamWriter) -> None:
        self.client_writers.append(writer)

    def rem_client(self, writer: StreamWriter) -> None:

        if writer in self.client_writers:
            self.client_writers.remove(writer)

    async def splitter(self) -> None:

        # read from rtl_tcp and forward data if any
        while (True):

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


class RTLClient:

    def __init__(self, rtl: RTLSplitter) -> None:
        self.rtl = rtl

    async def callback(self, reader: StreamReader, writer: StreamWriter) -> None:

        print("-" * 60)
        self.rtl.add_client(writer)

        try:
            try:
                writer.write(self.rtl.header)
                await writer.drain()

                while (True):
                    data = await reader.read(5)

                    if b'' == data:
                        break

                    c, v = struct.unpack(">BI", data)

                    cmd = RTLCommand(c)

                    print(f"{cmd.name:<27} -> {v}")

                    await self.rtl.send_command(data)
            finally:
                self.rtl.rem_client(writer)
                writer.close()
                await writer.wait_closed()
        except asyncio.exceptions.CancelledError:
            pass
        except ConnectionResetError:
            pass


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

    async with RTLSplitter(args.target, args.port) as rtl:

        await asyncio.gather(
            server_loop(rtl, args.listen),
            rtl.splitter()
        )

    return status


if __name__ == '__main__':

    try:
        status = asyncio.run(main())
    except KeyboardInterrupt:
        status = 0

    if 0 != status:
        sys.exit(status)
