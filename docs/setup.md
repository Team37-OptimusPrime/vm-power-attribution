# Environment Setup Guide

> 환경 설정 가이드 - 재현 가능한 실험을 위한 상세 문서

---

## 1. 하드웨어 구성

### 1.1 Host Server (Alienware Aurora R12)

| 항목 | 사양 | 비고 |
|-----|------|------|
| CPU | Intel Core i7-11700KF | 8C/16T, 3.6GHz base |
| GPU | NVIDIA GeForce RTX 3060 | 12GB VRAM, 170W TDP |
| RAM | 32GB DDR4 | |
| Storage | NVMe SSD | |
| Network | Onboard + Intel I350-T2 | PTP 지원 |
| IP | 192.168.0.66 (static) | |
| SSH | 내부 포트 22 (외부 접속은 라우터 포트포워딩) | |

### 1.2 Power Measurement System (RPICT4V3)

| 구성품 | 모델 | 수량 | 역할 |
|-------|------|-----|------|
| HAT Board | RPICT4V3 Master | 1 | 전력 측정 메인 보드 |
| CT Sensor | SCT-006 (20A) | 3 | 전류 측정 |
| AC Adapter | AC/AC 어댑터 | 3 | 전압 측정 |
| SBC | Raspberry Pi 4 | 1 | 데이터 수집 |

### 1.3 네트워크 토폴로지

```
Internet
    |
[iptime Router] ─── KT ISP
    |
    ├── [Alienware: 192.168.0.66]
    │       └── [virbr0: 192.168.122.1]
    │               ├── VM1: 192.168.122.x
    │               ├── VM2: 192.168.122.x
    │               └── ...
    │
    └── [Raspberry Pi: 192.168.0.200]
            └── RPICT4V3 (Serial: /dev/ttyAMA0)
```

---

## 2. Host Server 설정

### 2.1 OS 설치

- Ubuntu 22.04 LTS Server
- 설치 시 OpenSSH 서버 포함

### 2.2 기본 패키지 설치

```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 필수 패키지
sudo apt install -y \
    build-essential \
    git \
    python3-pip \
    python3-venv \
    htop \
    tmux \
    vim
```

### 2.3 가상화 환경 설치

```bash
# KVM/QEMU + libvirt
sudo apt install -y \
    qemu-kvm \
    libvirt-daemon-system \
    libvirt-clients \
    bridge-utils \
    virt-manager

# 사용자를 libvirt 그룹에 추가
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER

# 서비스 시작
sudo systemctl enable libvirtd
sudo systemctl start libvirtd

# 확인
virsh list --all
```

### 2.4 NVIDIA 드라이버 및 CUDA

```bash
# NVIDIA 드라이버 (권장: 공식 .run 또는 apt)
sudo apt install nvidia-driver-570

# CUDA Toolkit 12.8
# https://developer.nvidia.com/cuda-downloads 참조

# 확인
nvidia-smi
nvcc --version
```

### 2.5 에너지 측정 도구

```bash
# 전력 측정 도구
sudo apt install -y \
    linux-tools-common \
    linux-tools-generic \
    linux-tools-$(uname -r) \
    powerstat

# perf 권한 설정 (RAPL 접근용)
echo 'kernel.perf_event_paranoid=0' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# RAPL 접근 확인
ls /sys/class/powercap/intel-rapl/
cat /sys/class/powercap/intel-rapl/intel-rapl:0/name  # package-0
```

### 2.6 Python 환경

```bash
# 프로젝트 디렉토리에서
cd ~/vm-power-attribution
python3 -m venv venv
source venv/bin/activate

# 필요 패키지
pip install -r requirements.txt
```

**requirements.txt**:

```
numpy
pandas
matplotlib
seaborn
scikit-learn
pyserial
psutil
libvirt-python
pynvml
```

### 2.7 SSH 설정

```bash
# /etc/ssh/sshd_config
Port 22  # 내부용
# 외부 접속은 라우터에서 <외부포트> → 22 포트포워딩

# 키 기반 인증 설정 (권장)
ssh-keygen -t ed25519
# 공개키를 ~/.ssh/authorized_keys에 추가
```

---

## 3. RPICT4V3 설정 (Raspberry Pi)

### 3.1 Raspberry Pi OS 설치

- Raspberry Pi OS Lite (64-bit) 권장
- Raspberry Pi Imager로 SD 카드 작성
- 초기 설정 시 SSH 활성화

### 3.2 고정 IP 설정

```bash
# /etc/dhcpcd.conf
interface eth0
static ip_address=192.168.0.200/24
static routers=192.168.0.1
static domain_name_servers=8.8.8.8
```

### 3.3 시리얼 포트 활성화

```bash
# raspi-config에서 Serial Port 활성화
sudo raspi-config
# Interface Options → Serial Port
# - Login shell: No
# - Serial hardware: Yes

# 재부팅
sudo reboot

# 확인
ls -la /dev/ttyAMA0
```

### 3.4 RPICT 배선

```
RPICT4V3 HAT
├── CT1 (Channel 1) ─── [SCT-006] ─── Alienware 전원 케이블
├── CT2 (Channel 2) ─── [SCT-006] ─── (여분)
├── CT3 (Channel 3) ─── [SCT-006] ─── (여분)
├── V1 (Voltage 1) ─── [AC Adapter] ─── 벽면 콘센트
└── Serial ─── /dev/ttyAMA0 ─── Raspberry Pi
```

**주의사항**:

- CT 센서 방향 확인 (화살표가 전류 흐름 방향)
- AC 어댑터는 측정 대상과 같은 회로에 연결
- 감전 주의: 전원 끈 상태에서 배선

### 3.5 RPICT 읽기 테스트

```bash
# 시리얼 터미널로 직접 확인
sudo apt install minicom
minicom -D /dev/ttyAMA0 -b 38400

# 예상 출력 (RPICT4V3 기본 형식):
# NodeID Power1 Power2 Power3 Vrms1 Vrms2 Vrms3
```

### 3.6 데이터 전송 스크립트

```python
# /home/pi/rpict_sender.py
import serial
import socket
import time

SERIAL_PORT = '/dev/ttyAMA0'
BAUD_RATE = 38400
SERVER_IP = '192.168.0.66'
SERVER_PORT = 5000

ser = serial.Serial(SERIAL_PORT, BAUD_RATE)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    line = ser.readline().decode('utf-8').strip()
    timestamp = time.time()
    data = f"{timestamp},{line}"
    sock.sendto(data.encode(), (SERVER_IP, SERVER_PORT))
```

### 3.7 systemd 서비스 등록

```bash
# /etc/systemd/system/rpict-sender.service
[Unit]
Description=RPICT Data Sender
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/rpict_sender.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable rpict-sender
sudo systemctl start rpict-sender
```

---

## 4. VM 생성 가이드

### 4.1 Ubuntu Server VM 생성

```bash
# ISO 다운로드
wget https://releases.ubuntu.com/22.04/ubuntu-22.04.3-live-server-amd64.iso \
    -O ~/iso/ubuntu-22.04-server.iso

# virt-install로 VM 생성
virt-install \
    --name vm1 \
    --ram 8192 \
    --vcpus 4 \
    --disk path=/var/lib/libvirt/images/vm1.qcow2,size=50 \
    --os-variant ubuntu22.04 \
    --network bridge=virbr0 \
    --graphics none \
    --console pty,target_type=serial \
    --cdrom ~/iso/ubuntu-22.04-server.iso
```

### 4.2 VM 리소스 프로파일

| 프로파일 | vCPU | RAM | 용도 |
|---------|------|-----|------|
| small | 2 | 4GB | 경량 테스트 |
| medium | 4 | 8GB | 기본 실험 |
| large | 6 | 16GB | 고부하 실험 |
| xlarge | 8 | 24GB | 최대 부하 |

### 4.3 GPU 패스스루 (선택)

```bash
# IOMMU 활성화 (/etc/default/grub)
GRUB_CMDLINE_LINUX="intel_iommu=on"

# grub 업데이트
sudo update-grub
sudo reboot

# GPU를 vfio-pci에 바인딩
# (상세 설정은 별도 문서 참조)
```

---

## 5. 시간 동기화

### 5.1 NTP 설정 (기본)

```bash
# Host (Alienware)
sudo apt install chrony
sudo systemctl enable chrony

# Raspberry Pi
sudo apt install chrony
# /etc/chrony/chrony.conf에 Host를 NTP 서버로 추가
server 192.168.0.66 iburst
```

### 5.2 PTP 설정 (고정밀, Intel I350 사용 시)

```bash
# linuxptp 설치
sudo apt install linuxptp

# PTP 마스터 (Alienware)
sudo ptp4l -i enp3s0f0 -m

# PTP 슬레이브 (Raspberry Pi)
sudo ptp4l -i eth0 -m -s

# 시스템 시간 동기화
sudo phc2sys -s /dev/ptp0 -w
```

---

## 6. 검증 체크리스트

### Host Server

- [ ] `virsh list --all` 정상 출력
- [ ] `nvidia-smi` GPU 인식
- [ ] `/sys/class/powercap/intel-rapl/` 접근 가능
- [ ] `powerstat` 실행 가능
- [ ] Python venv 활성화 및 패키지 설치

### Raspberry Pi

- [ ] 고정 IP 192.168.0.200 설정
- [ ] `/dev/ttyAMA0` 접근 가능
- [ ] RPICT 시리얼 데이터 수신 확인
- [ ] Host로 UDP 전송 확인

### 네트워크

- [ ] Host ↔ Raspberry Pi ping 가능
- [ ] 외부에서 SSH 접속 가능 (라우터 포트포워딩)
- [ ] VM에서 인터넷 접속 가능

### 시간 동기화

- [ ] Host와 Raspberry Pi 시간 차이 < 10ms
- [ ] (PTP 사용 시) 시간 차이 < 1ms

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-01 | 최초 작성 | Woorim Shin |
