# Assinatura do executável (Windows)

Sem assinatura, o Windows mostra "Editor desconhecido" e o SmartScreen pode avisar "O Windows protegeu o
computador" no primeiro uso. Com assinatura, aparece o nome da empresa (IGNF) e o aviso some com o tempo.

## Opções de certificado

| Opção | Custo aproximado | Observações |
|---|---|---|
| **Azure Artifact Signing** (antes "Trusted Signing") | ~US$ 10/mês | O mais barato. Exige empresa com 3+ anos de existência (ou pessoa física em alguns países); validação pela Microsoft. Assina pela nuvem (sem arquivo .pfx). |
| Certificado OV (Sectigo, DigiCert, Certum…) | ~US$ 200–500/ano | Validação da empresa (CNPJ). Desde 2023 vem em token USB ou HSM na nuvem. |
| Certificado EV | ~US$ 400–700/ano | Reputação imediata no SmartScreen; também em token. |

Para começar, a recomendação é o **Azure Artifact Signing**, se a IGNF se enquadrar. Senão, um OV da **Certum**,
que é dos mais baratos.

## Como o build usa

`tools/build.py` assina o `IGNF-Finora.exe` antes de compactar quando encontra as variáveis:

- `FINORA_SIGN_PFX`: caminho do certificado .pfx;
- `FINORA_SIGN_PASS`: senha do .pfx.

Sem elas, o build segue sem assinar. Certificado em token ou na nuvem usa outra linha de comando do `signtool`
(ou a ferramenta do provedor): ajuste a função `sign()` quando o certificado chegar.

**Nunca** coloque o .pfx nem a senha no repositório. No GitHub Actions, use *Secrets*.
