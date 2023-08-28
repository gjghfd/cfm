#include <bits/stdc++.h>
using namespace std;
int is_first = 0;
char lst1, lst2;
char my_getchar() {     // record first two chars after '\n'
    char c = getchar();
    if (c == '\n') {
        is_first = 2;
    } else if (is_first == 2) {
        lst1 = c; is_first--;
    } else if (is_first == 1) {
        lst2 = c; is_first--;
    }
    return c;
}
int Read(float &x) {
    char c = my_getchar();
    for (; c < '0' || c > '9'; c = my_getchar()) {
        if (c == EOF) return -1;
    }
    for (x = 0; c >= '0' && c <= '9'; x = x * 10 + c - 48, c = my_getchar()) ;
    if (c == '.') {
        float pw = 0.1;
        for (c = my_getchar(); c >= '0' && c <= '9'; x += (c - 48) * pw, pw *= 0.1, c = my_getchar()) ;
    }
    if (c == EOF) return -1;
    return 0;
}
float get_slo(char c1, char c2) {
    #define SLO_RATE 1.2

    float base = 0;
    if (c1 == 'g' && c2 == 'r') {
        base = 35.547;
    } else if (c1 == 'q' && c2 == 'u') {
        base = 249.977;
    } else if (c1 == 'p' && c2 == 'a') {
        base = 167.774;
    } else if (c1 == 'i' && c2 == 'm') {
        base = 69.167;
    } else if (c1 == 'm' && c2 == 'a') {
        base = 263.057;
    } else if (c1 == 'm' && c2 == 'e') {
        base = 845.811;
    } else {
        printf("Error: c1 = %c, c2 = %c\n", c1, c2);
    }

    return base * SLO_RATE;
}
int main(int argc, const char **argv) {
    if (argc != 2) {
        printf("Please input filename.\n");
        return 0;
    }
    freopen(argv[1], "r", stdin);

    printf("Input the log file of CFM.\n");

    char c = my_getchar();
    while (c != 'N') c = my_getchar();
    int n = 0, total_slo = 0;
    double total_jct = 0;
    float id, arrival, sent, fin, jct, slo;
    while (true) {
        if (Read(id)) break;
        if (Read(arrival)) break;
        if (Read(sent)) break;
        if (Read(fin)) break;
        if (Read(jct)) break;
        if (Read(slo)) break;
        float required_slo = get_slo(lst1, lst2);
        int my_slo = jct <= required_slo ? 0 : 1;
        total_jct += jct;
        total_slo += my_slo;
        n++;
    }
    printf("%d %.3lf %d\n", n, total_jct / (double) n, total_slo);
    return 0;
}