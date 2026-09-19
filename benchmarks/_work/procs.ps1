Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|llama|node' } | ForEach-Object {
  $cl = ($_.CommandLine -replace '\s+',' ')
  if ($cl.Length -gt 140) { $cl = $cl.Substring(0,140) }
  "{0,-7} {1,-14} {2}" -f $_.ProcessId, $_.Name, $cl
}
