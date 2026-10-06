$ErrorActionPreference = 'Stop'
$students = @{
  Ori='d1yQtOSfobdzGs0XfzJlNw'; Nitay='Z1_SNYeGELFxRHXa0FQ0mA'
  Shahar='f3zvTU6e3-VF7o-tH60MKw'; Jonathan='M6kVHL-2USY2FS-Z8NsaSw'
  Neta='7MV16Jz1XONu10BcysVALA'; Alma='oye-ZE5ifVM93WUOZ2l0bQ'
}
foreach ($student in $students.GetEnumerator() | Sort-Object Name) {
  $siteUrl='https://epicori09-cmyk.github.io/shahaf-schedule-sync/students/'+$student.Value+'/'
  $workerUrl='https://shahaf-profile-admin.trading-api-9de14d.workers.dev/public/profiles/'+$student.Value+'/wake.json'
  $pages=Invoke-RestMethod ($siteUrl+'wake.json?audit='+[guid]::NewGuid()) -TimeoutSec 20
  $worker=Invoke-RestMethod $workerUrl -TimeoutSec 20
  $sw=(Invoke-WebRequest ($siteUrl+'sw.js?audit='+[guid]::NewGuid()) -TimeoutSec 20).Content
  if ($pages.profile_id -ne $student.Value -or $worker.profile_id -ne $student.Value -or $worker.next_alarm.profile_id -ne $student.Value) { throw 'Profile identity mismatch' }
  if ($worker.stale) { throw ('Stale live feed: '+$student.Name) }
  $generation=[datetimeoffset]::Parse($worker.generated_at)
  $age=[datetimeoffset]::UtcNow-$generation
  if ($age.TotalHours -gt 3 -or $age.TotalMinutes -lt -5) { throw ('Invalid feed age: '+$student.Name) }
  if ($worker.shortcut_action -notin @('set','clear','leave')) { throw 'Invalid root action' }
  if ($worker.shortcut_action -eq 'set') {
    $wake=[datetimeoffset]::Parse($worker.wake_at)
    $zone=[timezoneinfo]::FindSystemTimeZoneById('Israel Standard Time')
    $localNow=[timezoneinfo]::ConvertTime([datetimeoffset]::UtcNow,$zone)
    $localWake=[timezoneinfo]::ConvertTime($wake,$zone)
    $nextRing=$localNow.Date+$localWake.TimeOfDay
    if ($nextRing -le $localNow.DateTime) { $nextRing=$nextRing.AddDays(1) }
    if ($wake -le [datetimeoffset]::UtcNow -or $localWake.DateTime -ne $nextRing -or $localWake.ToString('yyyy-MM-dd') -ne $worker.next_school_day -or $localWake.DayOfWeek -in @('Friday','Saturday')) { throw ('Unsafe Clock occurrence: '+$student.Name) }
  }
  if ($worker.shortcut_action -eq 'clear' -and ($null -ne $worker.wake_at -or $null -ne $worker.wake_time)) { throw 'Inconsistent clear envelope' }
  if ($worker.next_alarm.alarm_control.command_version -notmatch '^[A-Za-z0-9_-]{43}$') { throw 'Missing live command version' }
  if ($sw -notmatch ('shahaf-schedule-'+[regex]::Escape($student.Value)+'-v7') -or $sw -notmatch 'relativePath === "wake.json"') { throw 'Service-worker bypass/version not deployed' }
  if ($student.Name -eq 'Ori' -and $worker.next_alarm.alarm_control.settings.wake_buffer_minutes -ne 75) { throw 'Unexpected Ori buffer setting' }
  if ($student.Name -eq 'Nitay' -and $worker.next_alarm.alarm_control.settings.wake_buffer_minutes -ne 25) { throw 'Nitay buffer changed' }
  [pscustomobject]@{name=$student.Name; action=$worker.shortcut_action; date=$worker.next_school_day; time=$worker.wake_time; preview_date=$worker.next_alarm.next_school_day; preview_time=$worker.next_alarm.wake_time; generated_at=$worker.generated_at; stale=$worker.stale; version_ok=$true; cache_v7=$true}
}
