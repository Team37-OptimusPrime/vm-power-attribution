# Troubleshooting Guide

> 문제 해결 가이드 - 발생한 이슈와 해결 방법 기록

---

## 1. Host Server (Alienware) 이슈

### 1.1 RAPL 접근 권한 오류

**증상**:

```
Permission denied: /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj
```

**원인**: 일반 사용자에게 RAPL 읽기 권한 없음

**해결**:

```bash
# 방법 1: sudo로 실행
sudo python3 collect_rapl.py

# 방법 2: 권한 변경 (임시)
sudo chmod o+r /sys/class/powercap/intel-rapl/*/energy_uj

# 방법 3: udev 규칙 추가 (영구)
echo 'SUBSYSTEM=="powercap", ACTION=="add", RUN+="/bin/chmod o+r /sys/class/powercap/intel-rapl/*/energy_uj"' | sudo tee /etc/udev/rules.d/99-rapl.rules
sudo udevadm control --reload-rules
```

---

### 1.2 nvidia-smi 오류

**증상**:

```
NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.
```

**원인**: 드라이버 미설치 또는 커널 업데이트 후 드라이버 불일치

**해결**:

```bash
# 드라이버 상태 확인
lsmod | grep nvidia

# 드라이버 재설치
sudo apt install --reinstall nvidia-driver-570

# 또는 DKMS로 재빌드
sudo dkms install nvidia/570.211.01

# 재부팅
sudo reboot
```

---

### 1.3 libvirt 연결 실패

**증상**:

```
error: failed to connect to the hypervisor
error: Failed to connect socket to '/var/run/libvirt/libvirt-sock'
```

**원인**: libvirtd 서비스 미실행 또는 권한 문제

**해결**:

```bash
# 서비스 상태 확인
sudo systemctl status libvirtd

# 서비스 시작
sudo systemctl start libvirtd

# 사용자 그룹 확인
groups $USER  # libvirt, kvm 포함되어야 함

# 그룹 추가 (필요시)
sudo usermod -aG libvirt,kvm $USER
# 로그아웃 후 재로그인
```

---

### 1.4 VM 네트워크 연결 안됨

**증상**: VM에서 외부 네트워크 접속 불가

**원인**: virbr0 브릿지 미활성화 또는 IP 포워딩 비활성화

**해결**:

```bash
# 네트워크 상태 확인
virsh net-list --all

# default 네트워크 시작
virsh net-start default
virsh net-autostart default

# IP 포워딩 확인
cat /proc/sys/net/ipv4/ip_forward  # 1이어야 함

# IP 포워딩 활성화
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward
# 영구 설정: /etc/sysctl.conf에 net.ipv4.ip_forward=1 추가
```

---

## 2. Raspberry Pi / RPICT 이슈

### 2.1 시리얼 포트 접근 불가

**증상**:

```
[Errno 13] Permission denied: '/dev/ttyAMA0'
```

**원인**: 시리얼 포트 권한 부족

**해결**:

```bash
# dialout 그룹 추가
sudo usermod -aG dialout $USER

# 권한 확인
ls -la /dev/ttyAMA0  # crw-rw---- 1 root dialout

# 재로그인 후 테스트
```

---

### 2.2 RPICT 데이터 수신 안됨

**증상**: minicom에서 아무 데이터도 나오지 않음

**원인**:

1. 시리얼 콘솔이 시스템에 의해 사용 중
2. Baud rate 불일치
3. RPICT 전원 문제

**해결**:

```bash
# 시리얼 콘솔 비활성화 확인
sudo raspi-config
# Interface Options → Serial Port
# Login shell: No, Serial hardware: Yes

# Baud rate 확인 (RPICT4V3 기본: 38400)
minicom -D /dev/ttyAMA0 -b 38400

# RPICT LED 상태 확인 (전원 LED 점등 여부)
```

---

### 2.3 CT 센서 값이 0

**증상**: 전류 값이 항상 0으로 표시

**원인**:

1. CT 센서가 제대로 클램프되지 않음
2. CT 센서 방향이 반대
3. 측정 대상에 부하가 없음

**해결**:

1. CT 센서가 전선을 완전히 감싸는지 확인
2. CT 센서의 화살표 방향 확인 (전류 흐름 방향)
3. 측정 대상 장비를 켜고 부하 발생시킨 후 테스트

---

### 2.4 UDP 패킷 손실

**증상**: Host에서 수신되는 데이터에 gap 발생

**원인**: 네트워크 문제 또는 버퍼 오버플로우

**해결**:

```bash
# UDP 버퍼 크기 증가 (Host)
sudo sysctl -w net.core.rmem_max=26214400
sudo sysctl -w net.core.rmem_default=26214400

# TCP로 전환 (신뢰성 필요시)
# 또는 시퀀스 번호 추가하여 손실 감지
```

---

## 3. VM 워크로드 이슈

### 3.1 CUDA out of memory

**증상**:

```
RuntimeError: CUDA out of memory
```

**원인**: GPU 메모리 부족 또는 이전 프로세스가 메모리 점유

**해결**:

```bash
# GPU 프로세스 확인
nvidia-smi

# 좀비 프로세스 종료
sudo fuser -v /dev/nvidia*
sudo kill -9 <PID>

# 배치 크기 줄이기
# 또는 torch.cuda.empty_cache() 호출
```

---

### 3.2 PyTorch에서 GPU 인식 안됨

**증상**:

```python
>>> torch.cuda.is_available()
False
```

**원인**: CUDA 버전 불일치 또는 드라이버 문제

**해결**:

```bash
# CUDA 버전 확인
nvcc --version
nvidia-smi  # CUDA Version 확인

# PyTorch CUDA 버전 확인
python -c "import torch; print(torch.version.cuda)"

# 맞는 버전 재설치
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

---

## 4. 데이터 수집 이슈

### 4.1 타임스탬프 불일치

**증상**: RPICT, RAPL, nvidia-smi 데이터의 시간이 맞지 않음

**원인**: 시스템 간 시간 동기화 안됨

**해결**:

```bash
# NTP 동기화 확인
timedatectl status

# chrony 상태
chronyc tracking
chronyc sources

# 강제 동기화
sudo chronyc makestep
```

---

### 4.2 RAPL 에너지 카운터 오버플로우

**증상**: 에너지 값이 갑자기 감소

**원인**: 32비트 카운터 오버플로우 (약 65초마다)

**해결**:

```python
# 오버플로우 처리 코드
MAX_ENERGY = 2**32  # 또는 실제 max 값 확인

def handle_overflow(current, previous, max_val=MAX_ENERGY):
    if current < previous:
        return (max_val - previous) + current
    return current - previous
```

---

### 4.3 디스크 공간 부족

**증상**: 데이터 로깅 중 갑자기 중단

**원인**: 장시간 실험으로 디스크 가득 참

**해결**:

```bash
# 디스크 사용량 확인
df -h

# 로그 압축 (실시간)
# 스크립트에서 gzip 파이프라인 사용
python collect.py | gzip > data.csv.gz

# 오래된 데이터 정리
find data/raw -mtime +7 -name "*.csv" -exec gzip {} \;
```

---

## 5. 공통 체크리스트

### 실험 시작 전

- [ ] 디스크 여유 공간 > 10GB
- [ ] 모든 측정 스크립트 테스트 실행
- [ ] 시간 동기화 확인 (시스템 간 차이 < 1초)
- [ ] 불필요한 프로세스 종료
- [ ] tmux/screen 세션에서 실행 (SSH 끊김 대비)

### 실험 중 문제 발생 시

1. 모든 로그 파일 보존
2. 오류 메시지 전체 캡처
3. 시스템 상태 스냅샷 (`top`, `nvidia-smi`, `dmesg`)
4. 이 문서에 새 이슈 추가

---

## 이슈 히스토리

| 날짜 | 이슈 | 해결 | 소요 시간 |
|-----|------|------|----------|
| - | - | - | - |

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|-----|----------|-------|
| 2026-02-01 | 최초 작성 | Woorim Shin |
