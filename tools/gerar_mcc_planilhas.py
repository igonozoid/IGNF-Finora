"""Gera planilhas de exemplo no formato exportado pelo MCC original (tests/data/mcc_planilhas/).

Dados inventados, imitando o formato real (issue #5): Latin-1, ";", título + período + linha em branco (espaço do
logo) antes das colunas, rodapé de totais, observação com quebra de linha, cadastro com nome repetido, extrato com
o saldo final no rodapé e uma movimentação antiga de um lado só.

    python tools/gerar_mcc_planilhas.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "data" / "mcc_planilhas"
PERIODO = "Período de 01/01/2000 a 31/12/2030;"
ANALITICO = "DATA;DOCUMENTO;DESCRIÇÃO;NOME;VALOR;MOVSIT;VENCIMENTO;OBSERVAÇÃO;CONTA;CENTRO DE CUSTO;TIPO;"
EXTRATO = "DATA;MOV;NOME;TIPO;OBS;CRÉDITO;DÉBITO;"
CADASTRO = "DOCUMENTO;NOME;ENDEREÇO;BAIRRO;CIDADE;ESTADO;CEP;TELEFONE;E-MAIL;"

FILES = {
    "analitico-despesas.csv": [
        "Relatório de Movimentos;", PERIODO, " ;", ANALITICO,
        "05/01/2026;Boleto;ENERGIA ELÉTRICA ;ENERGIA SUL S.A.;R$ 300,00;V;10/01/2026;;Banco Azul;ADMINISTRATIVO;Desp;",
        "12/01/2026;Recibo;HONORÁRIOS;CONTÁBIL EXEMPLO LTDA;R$ 450,00;V;02/01/2026;Honorários R$400 ",
        "Funcionários R$50;Caixa;ADMINISTRATIVO;Desp;",
        "20/01/2026;Recibo;HONORÁRIOS;CONTÁBIL EXEMPLO LTDA;R$ 450,00;V;02/02/2026;;Caixa;ADMINISTRATIVO;Desp;",
        "25/01/2026;Débito;TARIFA;BANCO VERDE;R$ 30,00;V;25/01/2026;;Banco Verde;;Desp;",
        "01/02/2026;NF 12;ADUBO;Agro Insumos;R$ 1.000,00;P;15/03/2026;;Banco Azul;LAVOURA;Desp;",
        ";;;;R$ 2.230,00;;;;;;;",
    ],
    "analitico-receitas.csv": [
        "Relatório de Movimentos;", PERIODO, " ;", ANALITICO,
        "10/01/2026;NF 1;VENDA DE MEL;MARIA CLIENTE;R$ 2.000,00;V;15/01/2026;;Banco Azul;LAVOURA;Rec.;",
        "01/03/2026;NF 2;VENDA DE MEL;Maria Cliente;R$ 500,00;P;30/03/2026;;Banco Azul;;Rec.;",
        ";;;;R$ 2.500,00;;;;;;;",
    ],
    "contas.csv": [
        "Relatório de saldo de contas;", PERIODO, " ;", "CONTA;SALDO EM 01/01/2000;",
        "Banco Azul;R$ 1.000,00;", "Caixa;R$ 0,00;", "Banco Verde;R$ 50,00;", ";R$ 1.050,00;",
        "CONTA;SALDO EM 01/01/2000;", "Banco Azul;R$ 1.000,00;", "Caixa;R$ 0,00;", "Banco Verde;R$ 50,00;",
        ";R$ 1.050,00;",
    ],
    "extrato-banco-azul.csv": [
        "Extrato de conta bancária;", PERIODO, " ;", EXTRATO,
        "10/01/2026;PAGTO.: ENERGIA ELÉTRICA ;ENERGIA SUL S.A.;Desc;;;R$ 300,00;",
        "15/01/2026;REC.: VENDA DE MEL;MARIA CLIENTE;Cred;;R$ 2.000,00;;",
        "20/01/2026;RETIRADA;                    ;Desc;Troco do caixa;;R$ 200,00;",
        ";;;;;R$ 2.000,00;R$ 500,00;",
        "Conta: Banco Azul  -  Saldo até 31/12/1999: R$ 1.000,00    Saldo final em 31/12/2030: R$ 2.500,00;",
    ],
    "extrato-caixa.csv": [
        "Extrato do caixa interno;", PERIODO, " ;", EXTRATO,
        "05/12/2025;DEPOSITADO EM CONTA BANCÁRIA;                    ;Desc;Antigo;;R$ 100,00;",
        "02/01/2026;PAGTO.: HONORÁRIOS;CONTÁBIL EXEMPLO LTDA;Desc;;;R$ 450,00;",
        "20/01/2026;RETIRADO DE CONTA BANCÁRIA;                    ;Cred;;R$ 200,00;;",
        "02/02/2026;PAGTO.: HONORÁRIOS;CONTÁBIL EXEMPLO LTDA;Desc;;;R$ 450,00;",
        ";;;;;R$ 200,00;R$ 1.000,00;",
        "Caixa Interno:     Saldo até 31/12/1999: R$ 0,00    Saldo final em 31/12/2030: R$- 700,00;",
    ],
    "clientes.csv": [
        "Relatório de Clientes;", ";", " ;", CADASTRO,
        ";MARIA CLIENTE;;;;;;;;",
        "529.982.247-25;MARIA CLIENTE;Rua das Flores, 10;Centro;Maria da Fé;MG;37.517-000;35 3662-0000;maria@exemplo.test;",
        ";MARIA CLIENTE;;;;;;;;",
        ";;;;;;;;;",
    ],
    "fornecedores.csv": [
        "Relatório de Fornecedores;", ";", " ;", CADASTRO,
        ";;;;;;;;;",
        "11.222.333/0001-81;CONTÁBIL EXEMPLO LTDA;Av. Brasil, 100;Centro;Itajubá;MG;37.500-000;35 3622-0000;;",
        ";CONTÁBIL EXEMPLO LTDA;;;;;;;;",
        ";ENERGIA SUL S.A.;;;;;;;;",
        ";;;;;;;;;",
    ],
    "centros-fluxo.csv": [
        "Relatório de fluxo de caixa por Centro de Custo;", PERIODO, " ;",
        "CENTRO DE CUSTO;TOTAL PAGO;TOTAL RECEBIDO;TOTAL A PAGAR;TOTAL A RECEBER;SALDO REALIZADO;SALDO PREVISTO;",
        "ADMINISTRATIVO;R$ 1.200,00;R$ 0,00;R$ 0,00;R$ 0,00;-R$ 1.200,00;R$ 0,00;",
    ],
    "anotacoes.csv": ["Minha planilha;", "A;B;C;", "1;2;3;"],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, lines in FILES.items():
        (OUT / name).write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))
    print(f"{len(FILES)} planilhas em {OUT}")


if __name__ == "__main__":
    main()
