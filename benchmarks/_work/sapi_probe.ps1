Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
Write-Output ("default voice: " + $s.Voice.Name + " / " + $s.Voice.Culture.Name)
$s.SelectVoice('Microsoft Huihui Desktop')
Write-Output ("after select: " + $s.Voice.Name + " / " + $s.Voice.Culture.Name)
$out = "X:\AI\LocalVoiceAgent\benchmarks\_work\sapi_huihui.wav"
$s.SetOutputToWaveFile($out)
$s.Speak("你好，我想测试一下本地语音识别系统。")
$s.Dispose()
Write-Output ("written: " + (Test-Path $out))
