# Editor de vídeo (Mahra e outros projetos)

Kit de edição automática usado pelo Claude nas sessões na nuvem.
Não faz parte do site; o `index.html` continua sendo a única página.

## Instalar

```bash
bash editor-video/install.sh
```

O script pode ser rodado várias vezes; ele instala em `/opt` e cria o comando `mahra-edit`.
Os modelos de IA (Whisper, BEN2, SAM 2, Depth Anything, CLAP) são baixados na primeira vez que cada um é usado.

## Fluxo padrão de um Reel

```bash
mahra-edit clean-audio bruto.mp4 01_audio.mp4                     # Demucs + limpeza + volume -14 LUFS
mahra-edit transcribe 01_audio.mp4 --out transcricao              # WhisperX palavra por palavra (--brand neutro p/ outros)
mahra-edit cut 01_audio.mp4 transcricao/words.json 02_cortado.mp4 # tira silêncios (--fillers, --remove 12.5-18)
mahra-edit reframe 02_cortado.mp4 03_vertical.mp4                 # 9:16 seguindo o rosto (YuNet)
mahra-edit render 03_vertical.mp4 04_legendado.mp4 --words 02_cortado.words.json --titles titulos.json
mahra-edit mix 04_legendado.mp4 musica.mp3 05_musica.mp4          # música com ducking
mahra-edit export 05_musica.mp4 final.mp4 --preset reels          # reels | tiktok | shorts | youtube | feed | quadrado
```

Extras:

| Comando | Ferramenta | Uso |
|---|---|---|
| `scenes` | PySceneDetect | lista as trocas de cena |
| `cutout` | BEN2 | recorta pessoa/produto (imagem → PNG, vídeo → WebM com transparência; use em `render --fg` para texto atrás da pessoa) |
| `depth` | Depth Anything V2 | mapa de profundidade ou `--blur 12` para desfoque de fundo tipo lente |
| `music` | CLAP | ordena as músicas de uma pasta pela descrição ("calma, luxuosa, árabe") |
| SAM 2 | sam2 (Python) | recorte de um objeto específico com clique/caixa, usado direto em Python |
| HyperFrames | `npx skills add heygen-com/hyperframes -g -y` | animações e vinhetas extras |

`titulos.json`: `[{"text": "Novo perfume árabe", "start": 0, "end": 2.2}]`

## Marcas

Cada pasta em `brands/` tem um `brand.json` (cores, fontes, logo, chamada final e vocabulário da transcrição).

- `mahra`: bordô #8E0115, rosé #C77A86, Cormorant Garamond, logo clara na tela final, "Compre pelo link na bio".
- `neutro`: legenda branca grossa com destaque amarelo, sem logo e sem tela final.

Para criar outra marca, copie uma pasta, troque o `brand.json` e a logo, e use `--brand <nome>`.

## Observação

A máquina não tem GPU: legendas, cortes e enquadramento são rápidos; recorte de fundo quadro a quadro (BEN2/SAM 2) leva cerca de 1 a 1,5 min por segundo de vídeo.
