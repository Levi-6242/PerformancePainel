# O OS Creator mudou de repositório

**Desde 28/08/2026 o código do OS Creator não mora mais aqui.**

Ele foi para o repositório da organização, junto com o pacote `chamado_garantia`, que só ele usa:

> **https://github.com/Grid-Co-CODE/oem**

O que sobrou nesta pasta são arquivos que o git ignora — `build/`, `dist/`, `assets_cache.json`,
`.env` e credenciais. Não é código-fonte: é resto de build e estado local. Serve de backup até
você ter certeza de que o clone novo está funcionando; depois pode apagar a pasta inteira.

## Por que mudou

O código estava numa conta pessoal (`Levi-6242/PerformancePainel`) e só uma pessoa conseguia
publicar novas versões. A ideia é que cada área mantenha a própria parte do app — a Engenharia
primeiro — sem depender de ninguém para cada ajuste.

## Onde trabalhar agora

O clone de trabalho e de build fica **fora do OneDrive**, porque o sync corrompe o PyInstaller:

    C:\GridcoBuild\oem

É o mesmo caminho que o `release.py` usa para compilar. Edite e builde ali.

**Ao clonar em uma máquina nova**, o git não traz `.env`, `fracttal_login.txt` nem
`assets_cache.json` — são ignorados de propósito. Copie-os de um clone que já funcione, senão o
build falha: o `assets_cache.json` está no `datas` do `.spec`.

## O que NÃO mudou

- O deep link `gridos://` continua funcionando. Quem resolve é o registro do Windows
  (`HKCU\Software\Classes\gridos`), apontando para o `.exe` instalado — onde o código-fonte mora
  é irrelevante em tempo de execução.
- A rota `api_os_creator_fractall_usinas` da plataforma continua onde estava. O acoplamento entre
  os dois projetos é HTTP, não import.

**Cuidado que passou a existir:** as duas pontas do `gridos://` agora vivem em repositórios
diferentes — quem manda é `plataforma/templates/index.html`, quem recebe é `os_creator/main.py`.
Mudar o formato do link virou duas alterações coordenadas, e nada avisa se uma esquecer da outra.
