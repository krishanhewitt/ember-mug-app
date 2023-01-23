"""Tests for `ember_mug.connection`."""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak import BleakError
from bleak.backends.device import BLEDevice

from ember_mug.connection import INITIAL_ATTRS, UPDATE_ATTRS, EmberMugConnection
from ember_mug.consts import MugCharacteristic, TemperatureUnit
from ember_mug.data import Colour


@patch('ember_mug.connection.USES_BLUEZ', True)
def test_adapter_with_bluez(ember_mug):
    connection = EmberMugConnection(ember_mug, adapter='hci0')
    assert connection._client_kwargs['adapter'] == 'hci0'


@patch('ember_mug.connection.USES_BLUEZ', False)
def test_adapter_without_bluez(ember_mug):
    with pytest.raises(ValueError):
        EmberMugConnection(ember_mug, adapter='hci0')


@patch('ember_mug.connection.EmberMugConnection.update_initial')
@patch('ember_mug.connection.establish_connection')
@pytest.mark.asyncio
async def test_connect(mug_update_initial, mock_establish_connection, mug_connection):
    # Already connected
    mug_connection._client = AsyncMock()
    mug_connection._client.is_connected = True
    async with mug_connection:
        pass
    mock_establish_connection.assert_not_called()

    # Not connected
    mug_connection._client = None
    mug_connection.disconnect = AsyncMock()
    async with mug_connection:
        pass
    mock_establish_connection.assert_called()
    mug_update_initial.assert_called()
    assert mug_connection._client is not None
    mug_connection.disconnect.assert_called()


@patch('ember_mug.connection.logger')
@patch('ember_mug.connection.establish_connection')
@pytest.mark.asyncio
async def test_connect_error(
    mock_establish_connection: Mock,
    mock_logger: Mock,
    mug_connection: EmberMugConnection,
) -> None:
    mug_connection._client = None  # type: ignore[assignment]
    mock_establish_connection.side_effect = BleakError
    with pytest.raises(BleakError):
        await mug_connection.ensure_connection()
    msg, device, exception = mock_logger.error.mock_calls[0].args
    assert msg == "%s: Failed to connect to the mug: %s"
    assert device == mug_connection._device
    assert isinstance(exception, BleakError)


@patch('ember_mug.connection.logger')
@patch('ember_mug.connection.establish_connection')
@pytest.mark.asyncio
async def test_pairing_exceptions(
    mock_establish_connection: Mock,
    mock_logger: Mock,
    mug_connection: EmberMugConnection,
) -> None:
    mock_client = AsyncMock()
    mock_client.pair.side_effect = NotImplementedError
    mock_establish_connection.return_value = mock_client
    mug_connection.update_initial = AsyncMock()  # type: ignore[assignment]
    mug_connection.subscribe = AsyncMock()  # type: ignore[assignment]
    await mug_connection.ensure_connection()
    mock_logger.warning.assert_called_with(
        'Pairing not implemented. '
        'If your mug is still in pairing mode (blinking blue) tap the button on the bottom to exit.',
    )


@pytest.mark.asyncio
async def test_disconnect(mug_connection):
    mug_connection._client = AsyncMock()

    mug_connection._client.is_connected = False
    await mug_connection.disconnect()
    mug_connection._client.disconnect.assert_not_called()

    mug_connection._client.is_connected = True
    await mug_connection.disconnect()
    mug_connection._client.disconnect.assert_called()


def test_set_device(mug_connection: EmberMugConnection) -> None:
    new_device = BLEDevice(
        address='BA:36:a5:be:88:cb',
        name='Ember Ceramic Mug',
    )
    assert mug_connection.mug.device.address != new_device.address
    mug_connection.set_device(new_device)
    assert mug_connection.mug.device.address == new_device.address


@pytest.mark.asyncio
async def test_get_mug_meta(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'Yw====-ABCDEFGHIJ'
    meta = await mug_connection.get_meta()
    assert meta.mug_id == 'WXc9PT09'
    assert meta.serial_number == 'ABCDEFGHIJ'
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.MUG_ID.uuid)


@pytest.mark.asyncio
async def test_get_mug_battery(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'5\x01'
    battery = await mug_connection.get_battery()
    assert battery.percent == 53.00
    assert battery.on_charging_base is True
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.BATTERY.uuid)


@pytest.mark.asyncio
async def test_get_mug_led_colour(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\xf4\x00\xa1\xff'
    colour = await mug_connection.get_led_colour()
    assert colour.as_hex() == '#f400a1'
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LED.uuid)


@pytest.mark.asyncio
async def test_set_mug_led_colour(mug_connection):
    mug_connection.ensure_connection = AsyncMock()
    await mug_connection.set_led_colour(Colour(244, 0, 161))
    mug_connection.ensure_connection.assert_called_once()
    mug_connection._client.write_gatt_char.assert_called_once_with(
        MugCharacteristic.LED.uuid,
        bytearray(b'\xf4\x00\xa1\xff'),
    )


@pytest.mark.asyncio
async def test_get_mug_target_temp(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\xcd\x15'
    assert (await mug_connection.get_target_temp()) == 55.81
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TARGET_TEMPERATURE.uuid)


@pytest.mark.asyncio
async def test_set_mug_target_temp(mug_connection):
    mug_connection.ensure_connection = AsyncMock()
    await mug_connection.set_target_temp(55.81)
    mug_connection.ensure_connection.assert_called_once()
    mug_connection._client.write_gatt_char.assert_called_once_with(
        MugCharacteristic.TARGET_TEMPERATURE.uuid,
        bytearray(b'\xcd\x15'),
    )


@pytest.mark.asyncio
async def test_get_mug_current_temp(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\xcd\x15'
    assert (await mug_connection.get_current_temp()) == 55.81
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.CURRENT_TEMPERATURE.uuid)


@pytest.mark.asyncio
async def test_get_mug_liquid_level(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\n'
    assert (await mug_connection.get_liquid_level()) == 10
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LIQUID_LEVEL.uuid)


@pytest.mark.asyncio
async def test_get_mug_liquid_state(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\x06'
    assert (await mug_connection.get_liquid_state()) == 6
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.LIQUID_STATE.uuid)


@pytest.mark.asyncio
async def test_get_mug_name(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'Mug Name'
    assert (await mug_connection.get_name()) == 'Mug Name'
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.MUG_NAME.uuid)


@pytest.mark.asyncio
async def test_set_mug_name(mug_connection):
    mug_connection.ensure_connection = AsyncMock()
    with pytest.raises(ValueError):
        await mug_connection.set_name('Hé!')

    await mug_connection.set_name('Mug name')
    mug_connection.ensure_connection.assert_called()
    mug_connection._client.write_gatt_char.assert_called_once_with(
        MugCharacteristic.MUG_NAME.uuid,
        bytearray(b'Mug name'),
    )


@pytest.mark.asyncio
async def test_get_mug_udsk(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'abcd12345'
    assert (await mug_connection.get_udsk()) == 'YWJjZDEyMzQ1'
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.UDSK.uuid)


@pytest.mark.asyncio
async def test_set_mug_udsk(mug_connection):
    mug_connection.ensure_connection = AsyncMock()
    await mug_connection.set_udsk('abcd12345')
    mug_connection.ensure_connection.assert_called_once()
    mug_connection._client.write_gatt_char.assert_called_once_with(
        MugCharacteristic.UDSK.uuid,
        bytearray(b'YWJjZDEyMzQ1'),
    )


@pytest.mark.asyncio
async def test_get_mug_dsk(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'abcd12345'
    assert (await mug_connection.get_dsk()) == 'YWJjZDEyMzQ1'
    mug_connection._client.read_gatt_char.return_value = b'something else'
    assert (await mug_connection.get_dsk()) == "c29tZXRoaW5nIGVsc2U="
    mug_connection._client.read_gatt_char.assert_called_with(MugCharacteristic.DSK.uuid)


@pytest.mark.asyncio
async def test_get_mug_temperature_unit(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\x01'
    assert (await mug_connection.get_temperature_unit()) == TemperatureUnit.FAHRENHEIT
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TEMPERATURE_UNIT.uuid)
    mug_connection._client.read_gatt_char.reset_mock()
    mug_connection._client.read_gatt_char.return_value = b'\x00'
    assert (await mug_connection.get_temperature_unit()) == TemperatureUnit.CELSIUS
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.TEMPERATURE_UNIT.uuid)


@pytest.mark.asyncio
async def test_set_mug_temperature_unit(mug_connection):
    mug_connection.ensure_connection = AsyncMock()
    await mug_connection.set_temperature_unit(TemperatureUnit.CELSIUS)
    mug_connection.ensure_connection.assert_called_once()
    mug_connection._client.write_gatt_char.assert_called_once_with(
        MugCharacteristic.TEMPERATURE_UNIT.uuid,
        bytearray(b'\x00'),
    )


@pytest.mark.asyncio
async def test_mug_ensure_correct_unit(mug_connection):
    mug_connection.mug.temperature_unit = TemperatureUnit.CELSIUS
    mug_connection.mug.use_metric = True
    mug_connection.set_temperature_unit = AsyncMock(return_value=None)
    await mug_connection.ensure_correct_unit()
    mug_connection.set_temperature_unit.assert_not_called()
    mug_connection.mug.temperature_unit = TemperatureUnit.FAHRENHEIT
    await mug_connection.ensure_correct_unit()
    mug_connection.set_temperature_unit.assert_called_with(TemperatureUnit.CELSIUS)


@pytest.mark.asyncio
async def test_get_mug_battery_voltage(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'\x01'
    assert (await mug_connection.get_battery_voltage()) == 1
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.CONTROL_REGISTER_DATA.uuid)


@pytest.mark.asyncio
async def test_get_mug_date_time_zone(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'c\x0f\xf6\x00'
    date_time = await mug_connection.get_date_time_zone()
    assert date_time.timestamp() == 1661990400.0
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.DATE_TIME_AND_ZONE.uuid)


@pytest.mark.asyncio
async def test_read_firmware(mug_connection):
    mug_connection._client.read_gatt_char.return_value = b'c\x01\x80\x00\x12\x00'
    firmware = await mug_connection.get_firmware()
    assert firmware.version == 355
    assert firmware.hardware == 128
    assert firmware.bootloader == 18
    mug_connection._client.read_gatt_char.assert_called_once_with(MugCharacteristic.FIRMWARE.uuid)


@pytest.mark.asyncio
async def test_mug_update_initial(mug_connection):
    mug_connection._update_multiple = AsyncMock(return_value={})
    mug_connection.ensure_connection = AsyncMock()
    assert (await mug_connection.update_initial()) == {}
    mug_connection._update_multiple.assert_called_once_with(INITIAL_ATTRS)


@pytest.mark.asyncio
async def test_mug_update_all(mug_connection):
    mug_connection._update_multiple = AsyncMock(return_value={})
    mug_connection.ensure_connection = AsyncMock()
    assert (await mug_connection.update_all()) == {}
    mug_connection._update_multiple.assert_called_once_with(UPDATE_ATTRS)


@pytest.mark.asyncio
async def test_mug_update_multiple(mug_connection):
    mug_connection.get_name = AsyncMock(return_value='name')
    mug_connection.mug.update_info = AsyncMock()
    await mug_connection._update_multiple(('name',))
    mug_connection.mug.update_info.assert_called_once_with(name='name')


@pytest.mark.asyncio
async def test_mug_update_queued_attributes(mug_connection):
    mug_connection._queued_updates = set()
    assert (await mug_connection.update_queued_attributes()) == []
    mug_connection.get_name = AsyncMock(return_value='name')
    mug_connection.mug.update_info = AsyncMock()
    mug_connection._queued_updates = {'name'}
    await mug_connection.update_queued_attributes()
    mug_connection.mug.update_info.assert_called_once_with(name='name')


def test_mug_notify_callback(mug_connection):
    mug_connection._notify_callback(1, b'\x02')
    mug_connection._notify_callback(1, b'\x02')
    assert 2 in mug_connection._latest_events
    mug_connection._notify_callback(1, b'\x04')
    assert 4 in mug_connection._latest_events
    mug_connection._notify_callback(1, b'\x05')
    assert 5 in mug_connection._latest_events
    mug_connection._notify_callback(1, b'\x06')
    assert 6 in mug_connection._latest_events
    mug_connection._notify_callback(1, b'\x07')
    assert 7 in mug_connection._latest_events
    mug_connection._notify_callback(1, b'\x08')
    assert 8 in mug_connection._latest_events
    callback = Mock()
    mug_connection.register_callback(callback)
    mug_connection._notify_callback(1, b'\x09')
    assert 9 in mug_connection._latest_events
    callback.assert_not_called()
    assert mug_connection._queued_updates == {
        "battery",
        "target_temp",
        "current_temp",
        "liquid_level",
        "liquid_state",
        "battery_voltage",
    }
    mug_connection._latest_events = {}
    mug_connection._notify_callback(1, b'\x02')
    callback.assert_called_once()
    callback.reset_mock()
    mug_connection._notify_callback(1, b'\x02')
    callback.assert_not_called()
