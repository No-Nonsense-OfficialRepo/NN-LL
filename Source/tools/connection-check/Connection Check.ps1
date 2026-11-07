# Read-only report. Authentication and identity secrets are never exported.
$ErrorActionPreference='Stop'
$report=[ordered]@{utc=[DateTime]::UtcNow.ToString('o');computer=$env:COMPUTERNAME}
function Section($name,[scriptblock]$work) {
    Write-Host ('Checking '+$name+'...')
    try {$report[$name]=& $work} catch {$report[$name]=@{error=$_.Exception.Message}}
}
function Api($route) {
    $key=(Get-Content (Join-Path $env:ProgramData 'LAN Launcher\VLA\authtoken.secret') -Raw).Trim()
    $request=[Net.HttpWebRequest]::Create('http://127.0.0.1:47993/'+$route)
    $request.Proxy=$null; $request.Timeout=5000; $request.Headers.Add('X-ZT1-Auth',$key)
    $response=$request.GetResponse()
    try {
        $reader=[IO.StreamReader]::new($response.GetResponseStream())
        try {$reader.ReadToEnd()|ConvertFrom-Json} finally {$reader.Dispose()}
    } finally {$response.Dispose()}
}
Section 'windows' {
    $os=Get-CimInstance Win32_OperatingSystem
    @{caption=[string]$os.Caption;version=[string]$os.Version;lastBootUtc=$os.LastBootUpTime.ToUniversalTime().ToString('o')}
}
Section 'timeStatus' {& w32tm /query /status 2>&1 | Out-String}
Section 'clockOffsetSamples' {& w32tm /stripchart /computer:time.windows.com /dataonly /samples:3 2>&1 | Out-String}
Section 'vlaService' {
    $service=Get-CimInstance Win32_Service -Filter "Name='LanLauncherVLA'"
    @{state=[string]$service.State;path=[string]$service.PathName}
}
Section 'vlaStatus' {
    $s=Api 'status'
    [ordered]@{online=$s.online;node=$s.address;version=$s.version;tcpFallbackActive=$s.tcpFallbackActive;
      listeningOn=$s.config.settings.listeningOn;surfaceAddresses=$s.config.settings.surfaceAddresses;
      tcpFallbackAllowed=$s.config.settings.allowTcpFallbackRelay;portMapping=$s.config.settings.portMappingEnabled}
}
Section 'networks' {
    @(Api 'network')|ForEach-Object {@{id=[string]$_.id;status=[string]$_.status;portError=$_.portError;addresses=@($_.assignedAddresses)}}
}
Section 'peers' {
    @(Api 'peer')|ForEach-Object {@{node=$_.address;role=$_.role;latency=$_.latency;
      paths=@($_.paths|ForEach-Object {@{address=[string]$_.address;active=[bool]$_.active;lastReceive=$_.lastReceive;lastSend=$_.lastSend}})}}
}
Section 'roomListeners' {
    Get-NetTCPConnection -State Listen|Where-Object LocalPort -in 47800,47802,47803,47805,47993|
      ForEach-Object {@{address=[string]$_.LocalAddress;port=[int]$_.LocalPort;process=[int]$_.OwningProcess}}
}
Section 'runningLaunchers' {
    Get-CimInstance Win32_Process|Where-Object Name -match '^LAN (Host|Client).*\.exe$'|
      ForEach-Object {
        $hash=if($_.ExecutablePath){(Get-FileHash -LiteralPath $_.ExecutablePath).Hash}else{''}
        @{name=$_.Name;path=$_.ExecutablePath;sha256=$hash}
      }
}
Section 'firewall' {
    $programs=@((Join-Path $env:ProgramFiles 'LAN Launcher\VLA\vla-service.exe'))
    $programs+=@($report.runningLaunchers|ForEach-Object {$_.path}|Where-Object {$_})
    $rules=@(foreach($program in ($programs|Select-Object -Unique)) {
        Get-NetFirewallApplicationFilter -Program $program -ErrorAction SilentlyContinue|
          Get-NetFirewallRule -ErrorAction SilentlyContinue|Where-Object Enabled -eq True
    })
    foreach($rule in $rules) {
        $app=$rule|Get-NetFirewallApplicationFilter
        $port=$rule|Get-NetFirewallPortFilter
        $scope=$rule|Get-NetFirewallAddressFilter
        @{name=$rule.DisplayName;action=[string]$rule.Action;direction=[string]$rule.Direction;
          program=$app.Program;protocol=$port.Protocol;localPort=$port.LocalPort;remoteAddress=$scope.RemoteAddress}
    }
}
Section 'udpNatProbe' {
    $targets=@(@{name='Cloudflare';host='stun.cloudflare.com';port=3478},
      @{name='Google';host='stun.l.google.com';port=19302})
    foreach($target in $targets) {
        $target.address=([Net.Dns]::GetHostAddresses($target.host)|
          Where-Object AddressFamily -eq InterNetwork|Select-Object -First 1).ToString()
    }
    $udp=[Net.Sockets.UdpClient]::new(0)
    $udp.Client.ReceiveTimeout=4000
    try {
        $localPort=$udp.Client.LocalEndPoint.Port
        foreach($target in @($targets[0],$targets[1],$targets[0])) {
            $result=[ordered]@{server=$target.name;localPort=$localPort;destination=$target.address+':'+$target.port}
            try {
                $tx=[byte[]]::new(12)
                $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
                try {$rng.GetBytes($tx)} finally {$rng.Dispose()}
                [byte[]]$packet=@(0,1,0,0,0x21,0x12,0xa4,0x42)+$tx
                $null=$udp.Send($packet,$packet.Length,$target.address,$target.port)
                $remote=[Net.IPEndPoint]::new([Net.IPAddress]::Any,0)
                $data=$udp.Receive([ref]$remote)
                if($data.Length -lt 20 -or $data[0] -ne 1 -or $data[1] -ne 1 -or
                  $remote.Address.ToString() -ne $target.address -or
                  [Convert]::ToBase64String([byte[]]$data[8..19]) -ne [Convert]::ToBase64String($tx)) {
                    throw 'Invalid or unmatched STUN response'
                }
                $end=[Math]::Min($data.Length,20+$data[2]*256+$data[3])
                $offset=20
                while($offset+4 -le $end) {
                    $kind=$data[$offset]*256+$data[$offset+1]
                    $length=$data[$offset+2]*256+$data[$offset+3]
                    if($offset+4+$length -gt $end) {throw 'Truncated STUN attribute'}
                    if($kind -eq 32 -and $length -ge 8 -and $data[$offset+5] -eq 1) {
                        $mappedPort=($data[$offset+6]*256+$data[$offset+7]) -bxor 0x2112
                        $octets=@(); $cookie=@(0x21,0x12,0xa4,0x42)
                        for($i=0;$i -lt 4;$i++) {$octets+=($data[$offset+8+$i] -bxor $cookie[$i])}
                        $result.mapped=($octets -join '.')+':'+$mappedPort
                        break
                    }
                    $offset+=4+[int]([Math]::Ceiling($length/4.0)*4)
                }
                if(-not $result.Contains('mapped')) {throw 'No IPv4 mapping in response'}
            } catch {$result.error=$_.Exception.Message}
            $result
        }
    } finally {$udp.Dispose()}
}
Section 'recentJoinTiming' {
    $log=Join-Path $env:TEMP 'lanlauncher-join-timings.log'
    if(Test-Path -LiteralPath $log) {@([IO.File]::ReadAllLines($log)|Select-Object -Last 70)}
}
$target=Join-Path $PSScriptRoot 'Connection Report.json'
Write-Host 'Formatting report...'
$report|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $target -Encoding UTF8
Write-Output ('Report saved: '+$target)
