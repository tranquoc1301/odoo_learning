/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onWillUpdateProps } from "@odoo/owl";

export class Todoitem extends Component {
    static template = "awesome_owl.Todoitem";

    setup() {
        // reactive state
        this.state = useState({
            count: 0,
            loading: true,
            message: "",
        });

        // DOM refs (defined with t-ref in template)
        this.containerRef = useRef("containerRef");
        this.inputRef = useRef("inputRef");

        // lifecycle: before start (useful for async data)
        onWillStart(async () => {
            // example async work (RPC or fetch)
            await new Promise((r) => setTimeout(r, 200));
            this.state.loading = false;
        });

        // lifecycle: after mounting in DOM
        onMounted(() => {
            const el = this.containerRef.el;
            if (el) {
                
                el.setAttribute("data-widget", "Todoitem");
            }
            if (this.inputRef.el) {
                 this.inputRef.el.focus();
            }
        });

        // lifecycle: when props will update
        onWillUpdateProps((nextProps) => {
            // react to prop changes if needed
             console.log("next props", nextProps);
        });
    }

    increment() {
        this.state.count++;
    }

    onInput(ev) {
        this.state.message = ev.target.value;
    }

    reset() {
        this.state.count = 0;
        this.state.message = "";
    }
}