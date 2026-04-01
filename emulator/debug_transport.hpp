#pragma once

#include <string>
#include <string_view>

class IDebugTransport {
public:
    virtual ~IDebugTransport() = default;

    virtual bool readCommand(std::string& line) = 0;
    virtual void writeLine(std::string_view line) = 0;
};

class StdioDebugTransport : public IDebugTransport {
public:
    bool readCommand(std::string& line) override;
    void writeLine(std::string_view line) override;
};
