$ErrorActionPreference = 'Stop'
$students = @{
  Ori = 'd1yQtOSfobdzGs0XfzJlNw'
  Nitay = 'Z1_SNYeGELFxRHXa0FQ0mA'
  Shahar = 'f3zvTU6e3-VF7o-tH60MKw'
  Jonathan = 'M6kVHL-2USY2FS-Z8NsaSw'
  Neta = '7MV16Jz1XONu10BcysVALA'
  Alma = 'oye-ZE5ifVM93WUOZ2l0bQ'
}
$qaResults = foreach ($student in $students.GetEnumerator() | Sort-Object Name) {
  $baseUrl = 'https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/' + $student.Value
  $data = Invoke-RestMethod ($baseUrl + '/data.json?audit=' + [guid]::NewGuid())
  $pages = Invoke-RestMethod ($baseUrl + '/wake.json?audit=' + [guid]::NewGuid())
  $workerUrl = 'https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/' + $student.Value + '/wake.json'
  $worker = Invoke-RestMethod $workerUrl
  if ($data.id -ne $student.Value -or $pages.profile_id -ne $student.Value -or $worker.profile_id -ne $student.Value) { throw 'Profile identity mismatch' }
  if ($pages.shortcut_action -ne $worker.shortcut_action -or $pages.wake_at -ne $worker.wake_at) { throw ('Pages/Worker mismatch for ' + $student.Name) }
  if (-not $worker.next_alarm) { throw 'Missing next-schoolday preview' }
  if ($student.Name -eq 'Ori' -and $worker.wake_time -ne '06:45') { throw 'Ori special wake rule missing' }
  if ($student.Name -eq 'Nitay' -and $worker.wake_time -ne '07:20') { throw 'Nitay 25-minute buffer missing' }
  [pscustomobject]@{ name=$student.Name; profile_id=$student.Value; generated_at=$pages.generated_at; action=$worker.shortcut_action; date=$worker.next_school_day; wake_time=$worker.wake_time; next_date=$worker.next_alarm.next_school_day; next_time=$worker.next_alarm.wake_time; stale=$worker.stale; pages_worker_match=$true }
}
$qaResults | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'live-endpoints.json') -Encoding UTF8
$qaResults | Format-Table name,action,date,wake_time,next_date,next_time,stale,pages_worker_match
