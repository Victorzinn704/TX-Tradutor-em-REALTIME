$BASE = 'C:\Users\Desktop\realtime_translator'
$DESK = 'C:\Users\Desktop\Desktop'
$WS   = New-Object -ComObject WScript.Shell

function CriarAtalho($nome, $target, $cmdargs, $dir, $icon, $desc) {
    $path = "$DESK\$nome.lnk"
    $s = $WS.CreateShortcut($path)
    $s.TargetPath       = $target
    if ($cmdargs) { $s.Arguments        = $cmdargs }
    if ($dir)     { $s.WorkingDirectory = $dir     }
    if ($icon)    { $s.IconLocation     = $icon    }
    if ($desc)    { $s.Description      = $desc    }
    $s.WindowStyle = 1
    $s.Save()
    Write-Host "  [OK] $path"
}

Write-Host ""
Write-Host "Recriando atalhos na Area de Trabalho..."
Write-Host ""

# 1. Tradutor (principal)
CriarAtalho `
    "Tradutor de Audio" `
    "$BASE\rodar.bat" `
    $null `
    $BASE `
    "C:\Windows\System32\imageres.dll,109" `
    "Inicia o tradutor de audio em tempo real (RTX 5060 Ti + RedDragon)"

# 2. Diagnostico
CriarAtalho `
    "Diagnostico de Audio" `
    "$BASE\diagnostico.bat" `
    $null `
    $BASE `
    "C:\Windows\System32\imageres.dll,77" `
    "Verifica CUDA e lista dispositivos de audio"

# 3. Listar dispositivos
CriarAtalho `
    "Listar Dispositivos Audio" `
    "$BASE\listar_dispositivos.bat" `
    $null `
    $BASE `
    "C:\Windows\System32\imageres.dll,48" `
    "Lista todos os dispositivos de audio disponiveis"

# 4. Instalar (mantém)
CriarAtalho `
    "Instalar Tradutor Audio" `
    "$BASE\instalar.bat" `
    $null `
    $BASE `
    "C:\Windows\System32\imageres.dll,56" `
    "Instala dependencias (execute na primeira vez)"

Write-Host ""
Write-Host "Pronto! Verificando Arguments salvos..."
Write-Host ""

$WS2 = New-Object -ComObject WScript.Shell
foreach ($n in @("Tradutor de Audio","Diagnostico de Audio","Listar Dispositivos Audio")) {
    $s2 = $WS2.CreateShortcut("$DESK\$n.lnk")
    Write-Host "[$n]"
    Write-Host "  Target: $($s2.TargetPath)"
    Write-Host "  Args:   $($s2.Arguments)"
}
