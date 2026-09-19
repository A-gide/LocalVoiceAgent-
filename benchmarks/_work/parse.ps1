param([string]$Path)
$e = $null
$t = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$null, [ref]$e)
foreach ($x in $e) { "{0}: line {1} col {2} : {3}" -f $x.ErrorId, $x.Extent.StartLineNumber, $x.Extent.StartColumnNumber, $x.Message }
