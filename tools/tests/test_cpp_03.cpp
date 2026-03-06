#include <cstdio>

void build_string(void)
{
    printf("a");
    printf("b");
    printf("c");
    printf("d");
    printf("e");
}

class Logger {
public:
    void flush(void)
    {
        printf("f1");
        printf("f2");
        printf("f3");
        printf("f4");
        printf("f5");
    }
};
