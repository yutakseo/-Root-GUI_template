"""LS1506~12A-R(CE) four-channel LED-control module."""

from dataclasses import dataclass
from os import getenv

import serial


COM_PORT = getenv("LIGHT_SERIAL_PORT", "COM3")
BAUD_RATE = int(getenv("LIGHT_SERIAL_BAUDRATE", "9600"))
TIMEOUT_SECONDS = float(getenv("LIGHT_SERIAL_TIMEOUT", "1"))
OUTPUT_MAX = 255
CHANNEL_COUNT = 4
ACK = bytes((0x02, 0x06, 0x03))


class LightCommunicationError(RuntimeError):
    """Raised when the controller cannot accept a lighting command."""


@dataclass(frozen=True, slots=True)
class LightTransmission:
    channel: int
    percent: float
    value: int
    packet: bytes


def build_brightness_packet(channel: int, percent: float) -> LightTransmission:
    """Convert a UI percentage to one controller packet."""
    if not 1 <= channel <= CHANNEL_COUNT:
        raise ValueError(f"Unsupported channel: {channel}")
    if not 0 <= percent <= 100:
        raise ValueError(f"CH{channel}: brightness must be between 0 and 100")

    value = round(percent * OUTPUT_MAX / 100)
    packet = b"\x02" + str(channel).encode("ascii") + f"{value:03d}".encode("ascii") + b"\x03"
    return LightTransmission(channel=channel, percent=percent, value=value, packet=packet)


def send_transmissions(
    transmissions: tuple[LightTransmission, ...],
) -> tuple[LightTransmission, ...]:
    """Send packets in order, requiring one ACK for every channel."""

    try:
        with serial.Serial(
            port=COM_PORT,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT_SECONDS,
            write_timeout=TIMEOUT_SECONDS,
        ) as controller:
            for transmission in transmissions:
                controller.reset_input_buffer()
                controller.write(transmission.packet)
                controller.flush()
                response = controller.read(len(ACK))
                if response != ACK:
                    received = response.hex(" ").upper() or "none"
                    raise LightCommunicationError(
                        f"CH{transmission.channel}: no ACK received (RX={received})"
                    )
    except serial.SerialException as error:
        raise LightCommunicationError(
            f"Unable to open {COM_PORT} at {BAUD_RATE} bps: {error}"
        ) from error

    return transmissions


def set_channel_brightness(channel: int, percent: float) -> LightTransmission:
    """Set one channel and return only after its ACK is received."""
    transmission = build_brightness_packet(channel, percent)
    return send_transmissions((transmission,))[0]


def set_four_brightness(
    light_1: float,
    light_2: float,
    light_3: float,
    light_4: float,
) -> tuple[LightTransmission, ...]:
    """Set CH1~CH4 and return their verified transmissions."""
    return send_transmissions(
        tuple(
            build_brightness_packet(channel, percent)
            for channel, percent in enumerate((light_1, light_2, light_3, light_4), start=1)
        )
    )


if __name__ == "__main__":
    # Example: CH1=54%, CH2=30%, CH3=80%, CH4=100%
    for sent in set_four_brightness(54, 30, 80, 100):
        print(f"CH{sent.channel}: {sent.percent}% => {sent.value}, TX={sent.packet.hex(' ').upper()}")
