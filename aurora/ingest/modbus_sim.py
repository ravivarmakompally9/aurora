"""Modbus TCP edge link (FR-01).

`TwinModbusServer` exposes the twin's sensors as holding registers, the way a station PLC
would. `ModbusReader` is the AURORA data hub side: it polls the registers and decodes them.
Each metric is a signed 32-bit integer (two registers, big-endian) scaled by its factor.
"""
from __future__ import annotations

import asyncio
import logging

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import ModbusTcpServer

log = logging.getLogger(__name__)
MISSING = -(2 ** 31)  # sentinel for a sensor that reports nothing


def register_map(metrics: dict) -> dict[str, tuple[int, int]]:
    """metric -> (address, scale); two registers per metric."""
    return {m: (2 * i, scale) for i, (m, (_unit, scale)) in enumerate(sorted(metrics.items()))}


def encode(v: float | None, scale: int) -> list[int]:
    x = MISSING if v is None else int(round(v * scale))
    x &= 0xFFFFFFFF
    return [(x >> 16) & 0xFFFF, x & 0xFFFF]


def decode(hi: int, lo: int, scale: int) -> float | None:
    x = (hi << 16) | lo
    if x >= 2 ** 31:
        x -= 2 ** 32
    return None if x == MISSING else x / scale


class TwinModbusServer:
    def __init__(self, metrics: dict, host: str = "127.0.0.1", port: int = 5020):
        self.map = register_map(metrics)
        self.slave = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * (2 * len(self.map) + 2)))
        self.context = ModbusServerContext(slaves=self.slave, single=True)
        self.host, self.port = host, port
        self.server: ModbusTcpServer | None = None

    def publish(self, values: dict):
        for m, (addr, scale) in self.map.items():
            if m in values:
                self.slave.setValues(3, addr, encode(values[m], scale))

    async def start(self):
        self.server = ModbusTcpServer(self.context, address=(self.host, self.port))
        asyncio.create_task(self.server.serve_forever())
        await asyncio.sleep(0.05)
        log.info("Modbus twin server on %s:%d", self.host, self.port)

    async def stop(self):
        if self.server:
            await self.server.shutdown()


class ModbusReader:
    def __init__(self, metrics: dict, host: str = "127.0.0.1", port: int = 5020):
        self.map = register_map(metrics)
        self.n_regs = 2 * len(self.map)
        self.client = AsyncModbusTcpClient(host, port=port)

    async def read(self) -> dict[str, float | None]:
        if not self.client.connected:
            await self.client.connect()
        regs: list[int] = []
        for start in range(0, self.n_regs, 100):  # Modbus allows 125 registers per request
            rr = await self.client.read_holding_registers(start, count=min(100, self.n_regs - start), slave=1)
            if rr.isError():
                raise IOError(f"Modbus read failed: {rr}")
            regs += rr.registers
        return {m: decode(regs[a], regs[a + 1], s) for m, (a, s) in self.map.items()}

    def close(self):
        self.client.close()
