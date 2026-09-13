import serial

# Opening Serial Communication first to ESP32
comm = serial.Serial('COM4', baudrate=115200)

while True:
    arduinoData = comm.readline().decode('ascii').strip().split(';')
    print(arduinoData);
