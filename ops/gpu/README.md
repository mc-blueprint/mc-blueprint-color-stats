# GPU推論環境

## 方針

- UbuntuホストにはUbuntu推奨のNVIDIAドライバーを導入する。CUDA Toolkitはシステムに導入しない。
- PyTorchのCUDA同梱wheelを一時venvに導入する。リポジトリ依存には追加しない。
- WSL2ではWindows側のNVIDIAドライバーを使い、WSL内にLinux用NVIDIAドライバーを導入しない。

## Ubuntuホスト

推奨ドライバーを確認して導入する。

```sh
ubuntu-drivers devices
sudo apt-get update
sudo apt-get install -y nvidia-driver-595-open
```

カーネルモジュールを有効にするため再起動が必要。再起動後に `uptime -s`、`nvidia-smi` で起動時刻、GPU名、VRAM、ドライバー版、CUDA版を確認する。

ホストごとの一時環境:

```sh
# ubuntu-1
sudo apt-get install -y python3-venv
sudo mkdir -p /opt/colorstats/venvs
sudo python3 -m venv /opt/colorstats/venvs/gpucheck
sudo /opt/colorstats/venvs/gpucheck/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128

# ubuntu-2
sudo apt-get install -y python3-venv
sudo mkdir -p /mnt/data/venvs
sudo python3 -m venv /mnt/data/venvs/gpucheck
sudo /mnt/data/venvs/gpucheck/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
```

再起動後の確認:

```sh
uptime -s
nvidia-smi
/opt/colorstats/venvs/gpucheck/bin/python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0)); x=torch.randn((512,512)).cuda(); y=x@x; torch.cuda.synchronize(); print(y.shape, y.device)'
```

ubuntu-2ではvenvのパスを `/mnt/data/venvs/gpucheck/bin/python` に置き換える。

## WSL2

Ubuntu 24.04を新しい専用ディストリビューションとしてH:上に作成する。既存ディストリビューションには操作しない。

```powershell
wsl --install --distribution Ubuntu-24.04 --location H:\WSL\colorstats --no-launch
wsl --set-version Ubuntu-24.04 2
```

初回起動後、Ubuntu内でPython venvを作り、CUDA対応PyTorch wheelを入れる。

```sh
sudo apt-get update
sudo apt-get install -y python3-venv
sudo mkdir -p /opt/colorstats/venvs
sudo python3 -m venv /opt/colorstats/venvs/gpucheck
sudo /opt/colorstats/venvs/gpucheck/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
nvidia-smi
/opt/colorstats/venvs/gpucheck/bin/python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0)); x=torch.randn((512,512)).cuda(); y=x@x; torch.cuda.synchronize(); print(y.shape, y.device)'
```

PyTorch wheelはCUDA runtimeと必要ライブラリをvenv内へ含む。`nvidia-smi` のCUDA表示はドライバーがサポートする上限であり、PyTorchの実行runtime版は `torch.version.cuda` で確認する。

## 実施結果（2026-11-01）

- ubuntu-1: `nvidia-driver-595-open` 595.99.02は前任が導入済み。再起動待ち。
- ubuntu-2: RTX 4070を確認し、`nvidia-driver-595-open` を導入。再起動待ち。カーネルドライバーは未ロードで、現時点の `nvidia-smi` は失敗。
- ubuntu-1/2: 各指定パスに一時venvとPyTorch `2.11.0+cu128` を導入済み。再起動前のためGPU実行は未確認。
- WSL2: `Ubuntu-24.04`（Ubuntu 24.04.5 LTS）を `H:\WSL\colorstats` に新規作成。`nvidia-smi` はGeForce RTX 4070 SUPER、driver 615.78.05、CUDA UMD 13.4を表示。WSL内にLinux用NVIDIAドライバーパッケージがないことを確認。
- WSL2: PyTorch `2.11.0+cu128`、`torch.version.cuda=12.8`、`torch.cuda.is_available()=True`、GPU名 `NVIDIA GeForce RTX 4070 SUPER`。512×512 CUDA行列積が完了し、結果は `cuda:0` 上。
- ubuntu-1の `uptime -s` は `2026-11-01 04:27:34`、ubuntu-2は `2026-11-01 04:27:46`。導入後の再起動はまだ。再起動後に `nvidia-smi` と上記PyTorch確認を実施する。

## 再起動後の確認（2026-11-01）

| ホスト | GPU | VRAM | Driver | `nvidia-smi` CUDA | PyTorch / runtime CUDA | CUDA演算 |
| --- | --- | ---: | --- | --- | --- | --- |
| ubuntu-1 | NVIDIA GeForce RTX 4060 | 8188 MiB | 595.99.02 | 13.2 | 2.11.0+cu128 / 12.8 | 512×512行列積成功、`cuda:0`、結果は有限値 |
| ubuntu-2 | NVIDIA GeForce RTX 4070 | 12282 MiB | 595.99.02 | 13.2 | 2.11.0+cu128 / 12.8 | 512×512行列積成功、`cuda:0`、結果は有限値 |

両機で `torch.cuda.is_available()` は `True`。`nvidia-smi`のCUDA版はドライバーがサポートする版、PyTorch runtime版は `torch.version.cuda` の値であり、表示値が異なるのは想定どおり。確認時にNumPy未導入の警告が出たが、CUDA演算には影響せず、行列積は同期後に完了した。

## 再起動時の有線LAN名変更

再起動後、旧netplan設定がインターフェース名に依存していたため、有線LANの名前変更と設定名が合わず、LANとSSHが一時利用できなくなった。前回起動ログではubuntu-2で `r8169` がデバイスを `eth0` として検出した後、カーネルが `enp4s0` へrenameした記録を確認した。ubuntu-1は前回起動ログで `eth0` として記録され、rename記録は見つからなかった。現在は両機ともnetplanの `match.macaddress` で物理NICを指定し、復旧している。

両ホストのパッケージログには、再起動前のsystemd/udev更新（255.4-1ubuntu8.17から255.4-1ubuntu8.18）があり、ubuntu-2ではLinuxカーネルも6.8.0-139から6.8.0-147へ更新されていた。起動ログではsystemd-udevdの命名scheme `v255` を確認した。これらの変更がrenameを発生させた要因として考えられるが、ログから直接の原因までは特定できず、NVIDIAドライバー導入との因果関係も未確定。カーネルコマンドラインにはインターフェース名を固定する指定はなかった。

今後の再起動でもNIC名が変わる可能性がある。netplanは現在のMAC照合設定を維持し、再起動前にSSH以外の復旧手段を確保する。再起動後にLAN/SSHへ接続できない場合は、コンソールで `ip -br link` とMACアドレスを確認し、netplanのMAC照合設定を確認する。GPU確認は `nvidia-smi` と一時venvのPyTorch CUDA演算で行う。
