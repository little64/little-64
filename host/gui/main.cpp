#include "app.hpp"
#include <iostream>

int main() {
    App app;
    if (!app.init()) {
        std::cerr << "Failed to initialize application\n";
        return 1;
    }
    app.run();
    app.shutdown();
    return 0;
}
