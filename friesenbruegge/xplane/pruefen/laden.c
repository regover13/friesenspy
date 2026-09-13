/* Laedt die gebaute .xpl und sucht XPluginStart. Die XPLM-Symbole bleiben dabei
 * unaufgeloest -- genau wie in X-Plane, das sie erst beim Laden bereitstellt.
 * Das ist der einzige Ladetest, den die Linux-Fassung vor dem ersten Piloten bekommt. */
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char** argv) {
    if (argc < 2) { fprintf(stderr, "Aufruf: laden <datei.xpl>\n"); return 2; }
    void* h = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    void* s = dlsym(h, "XPluginStart");
    printf("XPluginStart: %s\n", s ? "gefunden" : "FEHLT");
    dlclose(h);
    return s ? 0 : 1;
}
