$c = Get-Content '.cookies.json' -Raw | ConvertFrom-Json
$req = 'ttwid','odin_tt','passport_csrf_token'
foreach($k in $req){
  $v = $c.$k
  if($v){ Write-Output ($k + ': SET (' + $v.Length + ' chars)') }
  else { Write-Output ($k + ': MISSING') }
}
Write-Output ("All cookie keys: " + (($c.PSObject.Properties.Name) -join ', '))
