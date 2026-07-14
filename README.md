# Bass Catcher

MP3などの音源からベース帯域とルート音候補を解析し、  
耳コピ・練習・ルート譜作成を補助するWindowsデスクトップアプリです。

## 背景

Bass Catcherは、バンドメンバーのベーシストが  
楽曲のルート音を耳で拾えず困っていたことをきっかけに開発を始めました。

完成された自動採譜ソフトを目指すのではなく、

- 原曲の中でベースが鳴っている位置を見つける
- 低音域の候補を時間軸上で追う
- 拍ごとのルート音候補を確認する
- 誤認識した音だけ人間が修正する
- 練習用のルート譜や音源を作る

という流れで、ベーシストの耳コピ負担を軽くすることを目的としています。

> ベースラインを完全自動で決めるのではなく、  
> 人間が耳で確かめるための手掛かりを増やすアプリです。

## 主な機能

- MP3 / WAV / FLAC / M4A / AAC / OGGの読み込み
- 再生・一時停止・停止
- シーク、5秒戻る・進む
- A-B区間ループ
- B0〜C4の縦鍵盤表示
- 再生位置へ追従するピッチタイムライン
- テンポ・拍位置の推定
- 楽曲キーの推定
- 拍ごとのルート音候補表示
- 候補音の確信度表示
- 低確信度候補の強調表示
- ルート音の手動修正
- REST指定
- 原曲 / ベース強調音源 / 分離ベース音源の切り替え
- テンポ変更
- キー変更
- 練習用WAVの生成
- ルート譜PDF出力
- CSV出力
- MusicXML出力
- 解析セッションの保存・再読み込み
- Windows EXE化

## 解析方式

Bass Catcherは、単純に「最も低く、最も音圧の高い音」を  
ルート音として採用するわけではありません。

通常解析では、以下を組み合わせています。

- 打楽器成分と持続音成分の分離
- ベース帯域の抽出
- pYINによる基音候補推定
- テンポと拍位置の解析
- 拍頭への重み付け
- 音圧と有声音確率
- 楽曲キーとの整合
- 前後の音程移動
- 短い誤検出の補正
- オクターブ誤認の補正

### 解析モード

| モード | 内容 |
| --- | --- |
| Precision DSP | 標準の高精度解析 |
| Fast | 処理速度を優先した解析 |
| AI Hybrid | Basic PitchとDSP解析を組み合わせるモード |

Demucsが導入されている場合は、原曲からベースを分離してから解析できます。

## 動作環境

- Windows 10 / 11
- Python 3.11
- PySide6
- librosa
- NumPy
- SciPy
- SoundFile
- ReportLab

AI機能を利用する場合は、追加でBasic Pitch、Demucs、PyTorch関連の環境が必要です。

## セットアップ

### 1. Python 3.11の仮想環境を有効化

現在の開発環境では、リポジトリ外に仮想環境を置いています。

```powershell
cd "C:\Users\Ryohei\Documents\GitHub\bass-catcher"

& "$env:USERPROFILE\.venvs\bass-catcher\Scripts\Activate.ps1"
```

PowerShellの実行ポリシーで拒否された場合のみ、次を実行します。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. 通常版をインストール

```powershell
.\install.ps1
```

### 3. AI解析機能もインストール

```powershell
.\install.ps1 -AI
```

AI版はモデルと推論環境を含むため、通常版より容量が大きくなります。

## 起動

```powershell
.\run.ps1
```

または、

```powershell
python -m app.main
```

## 基本的な使い方

1. `IMPORT AUDIO`から音源を読み込む
2. 解析モードを選ぶ
3. 必要に応じてDemucs分離を有効にする
4. `RUN ROOT ANALYSIS`を実行する
5. タイムラインと一覧表でルート候補を確認する
6. 誤認識した音を手動で修正する
7. A-Bループやテンポ変更を使って耳で確認する
8. PDF、CSV、MusicXMLまたは解析セッションを出力する

## 出力形式

### PDF

4拍単位でルート音候補を並べた、練習用のルート譜を出力します。

### CSV

解析時刻、ルート音、MIDI番号、確信度、音圧、修正状態を出力します。

### MusicXML

MuseScoreなどに読み込み、五線譜として追加編集できます。

### Bass Catcher Session

解析結果と手動修正内容をJSON形式で保存し、後から再開できます。

## 練習用音源

アプリ内で次の変更を指定し、新しいWAV音源を生成できます。

- テンポ：0.50〜1.50倍
- キー：-12〜+12半音

原曲を直接変更せず、練習用の別ファイルとして生成します。

## Windows EXEの作成

### フォルダ形式

```powershell
.\build_exe.ps1
```

生成先：

```text
dist\BassCatcher\BassCatcher.exe
```

### 単一EXE形式

```powershell
.\build_exe.ps1 -Mode onefile
```

生成先：

```text
dist\BassCatcher.exe
```

### AI機能を含める

```powershell
.\build_exe.ps1 -AI
```

または、

```powershell
.\build_exe.ps1 -Mode onefile -AI
```

AI機能を含むEXEは、モデルと推論ランタイムを同梱するため非常に大きくなります。

## プロジェクト構成

```text
bass-catcher/
├─ app/
│  ├─ main.py
│  ├─ main_window.py
│  ├─ models.py
│  ├─ audio_analysis.py
│  ├─ audio_processing.py
│  ├─ exporters.py
│  ├─ workers.py
│  └─ widgets/
├─ assets/
│  └─ bass_catcher.ico
├─ install.ps1
├─ run.ps1
├─ build_exe.ps1
├─ requirements.txt
├─ requirements-ai.txt
├─ README.md
├─ .gitignore
└─ LICENSE
```

## 精度について

音源分離や自動採譜には限界があります。

特に次のような音源では誤認識が起こりやすくなります。

- キックとベースの低音が強く重なる
- ベースに強い歪みやエフェクトがかかっている
- ギターやシンセがベース帯域まで鳴っている
- スライド、ゴーストノート、ハンマリングが多い
- コードの最低音とベースのルート音が一致しない
- ライブ録音やノイズの多い音源
- 極端に音量の小さいベース

解析結果は正解を保証するものではありません。  
演奏前には必ず原曲を再生し、耳で確認してください。

## プライバシー

通常の解析処理はローカル環境で実行します。  
読み込んだ音源を外部サーバーへアップロードする機能はありません。

著作権のある音源を扱う場合は、個人利用・バンド練習など、  
権利上認められた範囲で使用してください。

## 開発状況

現在はプロトタイプ開発中です。

今後の候補：

- コード進行候補の表示
- 小節線と拍子の手動補正
- TAB譜出力
- ベースポジション候補
- セクションマーカー
- 波形表示
- Undo / Redo
- キーボードショートカット
- 解析結果の比較
- 推定精度の評価機能

## License

MIT License
